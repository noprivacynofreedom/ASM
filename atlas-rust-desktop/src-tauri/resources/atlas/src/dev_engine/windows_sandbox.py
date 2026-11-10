"""Windows Sandbox VM runner for approved Atlas build/test checks.

This is intentionally separate from MCP dispatch and desktop process ownership.
It launches Windows Sandbox (a disposable Hyper-V-backed guest), maps only the
selected disposable workspace writable, and maps its control files read-only.
No arbitrary command strings are accepted.
"""
from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from atlas_dev_engine import CHECKS, DevWorkspace, WorkspaceError

SANDBOX_CHECKS = {
    "python_tests": ("python.exe", ["-m", "pytest", "-q"], 180),
    "python_compile": ("python.exe", ["-m", "compileall", "-q", "."], 90),
    "npm_build": ("npm.cmd", ["run", "build"], 240),
    "npm_tests": ("npm.cmd", ["test", "--", "--run"], 240),
    "cargo_check": ("cargo.exe", ["check", "--locked"], 300),
    "cargo_tests": ("cargo.exe", ["test", "--locked"], 300),
    "dotnet_test": ("dotnet.exe", ["test", "--nologo"], 300),
    "go_test": ("go.exe", ["test", "./..."], 300),
}

RUNNER_PS1 = r'''param([Parameter(Mandatory=$true)][string]$ConfigPath)
$ErrorActionPreference = 'Stop'
# Optional read-only portable toolchain mount; tools must be provisioned by the host.
if (Test-Path 'C:\AtlasToolchain') { $env:PATH = 'C:\AtlasToolchain;C:\AtlasToolchain\bin;' + $env:PATH }
$cfg = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$root = 'C:\AtlasWorkspace'
$out = 'C:\AtlasResults'
$cwd = $root
if ($cfg.subdir -ne '.') { $cwd = Join-Path $root $cfg.subdir }
$resolvedRoot = [IO.Path]::GetFullPath($root).TrimEnd('\\') + '\\'
$resolvedCwd = [IO.Path]::GetFullPath($cwd)
if (-not ($resolvedCwd + '\\').StartsWith($resolvedRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'Working directory escaped workspace' }
if (-not (Test-Path -LiteralPath $resolvedCwd -PathType Container)) { throw 'Working directory missing' }
$commands = @{
 'python_tests' = @{ exe='python'; args=@('-m','pytest','-q'); timeout=180 }
 'python_compile' = @{ exe='python'; args=@('-m','compileall','-q','.'); timeout=90 }
 'npm_build' = @{ exe='npm'; args=@('run','build'); timeout=240 }
 'npm_tests' = @{ exe='npm'; args=@('test','--','--run'); timeout=240 }
 'cargo_check' = @{ exe='cargo'; args=@('check','--locked'); timeout=300 }
 'cargo_tests' = @{ exe='cargo'; args=@('test','--locked'); timeout=300 }
 'dotnet_test' = @{ exe='dotnet'; args=@('test','--nologo'); timeout=300 }
 'go_test' = @{ exe='go'; args=@('test','./...'); timeout=300 }
}
if (-not $commands.ContainsKey([string]$cfg.check)) { throw 'Check is not allowlisted' }
$spec = $commands[[string]$cfg.check]
$exe = Get-Command $spec.exe -CommandType Application -ErrorAction SilentlyContinue
function Read-Tail([string]$Path) { if (-not (Test-Path -LiteralPath $Path)) { return '' }; $v = Get-Content -LiteralPath $Path -Raw -ErrorAction SilentlyContinue; if ($null -eq $v) { return '' }; if ($v.Length -gt 30000) { return $v.Substring($v.Length - 30000) }; return $v }
$stdout = Join-Path $out 'stdout.txt'; $stderr = Join-Path $out 'stderr.txt'
$result = [ordered]@{ id=$cfg.id; check=$cfg.check; status='ERROR'; exit_code=$null; duration_seconds=0; stdout=''; stderr=''; guest='Windows Sandbox'; completed_at=[DateTime]::UtcNow.ToString('o') }
$timer = [Diagnostics.Stopwatch]::StartNew()
try {
  if (-not $exe) { throw "Required tool '$($spec.exe)' is not installed in the sandbox guest or mounted toolchain." }
  $p = Start-Process -FilePath $exe.Source -ArgumentList $spec.args -WorkingDirectory $resolvedCwd -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
  if (-not $p.WaitForExit($spec.timeout * 1000)) {
    & taskkill.exe /PID $p.Id /T /F | Out-Null
    $result.status = 'TIMEOUT'
  } else {
    $p.Refresh(); $result.exit_code = $p.ExitCode
    $result.status = if ($p.ExitCode -eq 0) { 'PASS' } else { 'FAIL' }
  }
} catch { $result.status='ERROR'; $result.stderr=$_.Exception.Message }
$timer.Stop(); $result.duration_seconds=[Math]::Round($timer.Elapsed.TotalSeconds,2)
$result.stdout = Read-Tail $stdout
$result.stderr += Read-Tail $stderr
$result.completed_at=[DateTime]::UtcNow.ToString('o')
$result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $out 'result.json') -Encoding UTF8
'''


def _xml_text(value: str) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


class WindowsSandboxRunner:
    """Prepare and launch one disposable Windows Sandbox for a fixed check."""

    def __init__(self, engine: DevWorkspace, toolchain_root: str | Path | None = None):
        self.engine = engine
        configured = toolchain_root or os.environ.get("ATLAS_SANDBOX_TOOLCHAIN_ROOT")
        self.toolchain_root = Path(configured).resolve() if configured else None

    def _sandbox_exe(self) -> str:
        if os.name != "nt":
            raise WorkspaceError("Windows Sandbox execution is available only on Windows 10/11 Pro, Enterprise, or Education with the Windows Sandbox feature enabled.")
        candidates = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "WindowsSandbox.exe"]
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        raise WorkspaceError("Windows Sandbox is not installed or enabled. Enable the Windows Sandbox optional feature and reboot.")

    def prepare(self, wid: str, check: str, subdir: str = ".") -> dict[str, Any]:
        if check not in SANDBOX_CHECKS or check not in CHECKS:
            raise WorkspaceError("Unsupported sandbox check.")
        ws = self.engine._workspace(wid)
        self.engine._assert_workspace_tree_safe(ws)
        rel = Path(".") if subdir in ("", ".") else Path(subdir.replace("\\", "/"))
        if rel.is_absolute() or any(p in ("..", "") for p in rel.parts):
            raise WorkspaceError("Sandbox working directory must be a safe relative workspace path.")
        cwd = ws / rel
        # Reject links in each component before resolving.
        cursor = ws
        for part in (() if str(rel) == "." else rel.parts):
            cursor = cursor / part
            if cursor.is_symlink() or getattr(cursor, "is_junction", lambda: False)():
                raise WorkspaceError("Sandbox working directory cannot traverse links or junctions.")
        if not cwd.is_dir():
            raise WorkspaceError("Sandbox working directory does not exist.")
        if check in ("npm_build", "npm_tests") and not (cwd / "package.json").is_file():
            raise WorkspaceError("No package.json in selected directory.")
        if check in ("cargo_check", "cargo_tests") and not (cwd / "Cargo.toml").is_file():
            raise WorkspaceError("No Cargo.toml in selected directory.")
        if check == "dotnet_test" and not any(cwd.glob("*.sln")) and not any(cwd.glob("*.csproj")):
            raise WorkspaceError("No .sln or .csproj file in selected directory.")
        if check == "go_test" and not (cwd / "go.mod").is_file():
            raise WorkspaceError("No go.mod in selected directory.")
        if check == "python_tests" and not any(cwd.glob("test*.py")) and not (cwd / "tests").exists():
            raise WorkspaceError("No Python tests found in selected directory.")

        run_id = uuid.uuid4().hex
        control = self.engine.root / "sandbox-control" / run_id
        staging = self.engine.root / "sandbox-staging" / wid / run_id
        results = self.engine.evidence_root / wid / f"sandbox-{run_id}"
        control.mkdir(parents=True, exist_ok=False)
        staging.parent.mkdir(parents=True, exist_ok=True)
        # Never expose the live agent workspace as a writable guest mount. The
        # guest receives a private disposable copy; its mutations cannot alter
        # the workspace being reviewed or another agent's work.
        shutil.copytree(ws, staging, symlinks=True)
        self.engine._assert_workspace_tree_safe(staging)
        results.mkdir(parents=True, exist_ok=False)
        config = {"id": run_id, "workspace": wid, "check": check,
                  "subdir": rel.as_posix() if str(rel) != "." else "."}
        (control / "runner.ps1").write_text(RUNNER_PS1, encoding="utf-8")
        (control / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
        (control / "results-path.txt").write_text(str(results), encoding="utf-8")
        return {"run_id": run_id, "workspace": wid, "check": check,
                "workspace_path": str(staging), "source_workspace_path": str(ws),
                "control_path": str(control), "results_path": str(results),
                "subdir": config["subdir"]}

    def build_wsb(self, prepared: dict[str, Any]) -> Path:
        control = Path(prepared["control_path"])
        ws = Path(prepared["workspace_path"])
        results = Path(prepared["results_path"])
        if os.name == "nt":
            for folder in (control, ws, results):
                raw = str(folder)
                if raw.startswith("\\\\") or not folder.drive:
                    raise WorkspaceError("Windows Sandbox mapped folders must be on a local drive, not a UNC/network path.")
        lines = ["<Configuration>", "  <VGpu>Disable</VGpu>", "  <Networking>Disable</Networking>",
                 "  <Clipboard>Disable</Clipboard>", "  <ProtectedClient>Enable</ProtectedClient>",
                 "  <MemoryInMB>4096</MemoryInMB>", "  <MappedFolders>"]
        for host, guest, readonly in ((control, r"C:\AtlasControl", True),
                                      (ws, r"C:\AtlasWorkspace", False),
                                      (results, r"C:\AtlasResults", False)):
            lines.extend(["    <MappedFolder>", f"      <HostFolder>{_xml_text(str(host))}</HostFolder>",
                          f"      <SandboxFolder>{guest}</SandboxFolder>",
                          f"      <ReadOnly>{'true' if readonly else 'false'}</ReadOnly>",
                          "    </MappedFolder>"])
        if self.toolchain_root:
            if not self.toolchain_root.is_dir():
                raise WorkspaceError("ATLAS_SANDBOX_TOOLCHAIN_ROOT does not exist.")
            lines.extend(["    <MappedFolder>",
                          f"      <HostFolder>{_xml_text(str(self.toolchain_root))}</HostFolder>",
                          r"      <SandboxFolder>C:\AtlasToolchain</SandboxFolder>",
                          "      <ReadOnly>true</ReadOnly>", "    </MappedFolder>"])
        lines.extend(["  </MappedFolders>", "  <LogonCommand>",
                      r"    <Command>powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File C:\AtlasControl\runner.ps1 -ConfigPath C:\AtlasControl\config.json</Command>",
                      "  </LogonCommand>", "</Configuration>"])
        path = control / "Atlas-Dev-Engine-Sandbox.wsb"
        path.write_text("\n".join(lines), encoding="utf-8")
        # Validate generated XML before any launch.
        ET.parse(path)
        return path

    def launch(self, wid: str, check: str, subdir: str = ".") -> dict[str, Any]:
        exe = self._sandbox_exe()  # fail before creating state if unavailable
        prepared = self.prepare(wid, check, subdir)
        wsb = self.build_wsb(prepared)
        try:
            proc = subprocess.Popen([exe, str(wsb)], shell=False, close_fds=True)
        except OSError as exc:
            raise WorkspaceError(f"Windows Sandbox could not be started: {exc}") from exc
        event = {"action": "sandbox_check_launched", "time": time.time(),
                 "run_id": prepared["run_id"], "workspace": wid, "check": check,
                 "sandbox_config": str(wsb), "launcher_pid": proc.pid,
                 "networking": "disabled", "clipboard": "disabled",
                 "workspace_mount": "read-write", "control_mount": "read-only",
                 "toolchain_mount": "read-only" if self.toolchain_root else None,
                 "status": "launched_not_yet_completed"}
        with self.engine.audit_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
        return {**event, "results_path": prepared["results_path"],
                "note": "Windows Sandbox is a separate guest. Build/test output appears in results_path after the guest completes. Results are untrusted until host-side review."}

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def verify_result(self, wid: str, run_id: str) -> dict[str, Any]:
        """Validate guest evidence structure and bind a host-side snapshot.

        A guest can fabricate its own JSON and output, so this verifies
        provenance/schema/consistency, not the truth of the reported test run.
        The returned trust label intentionally remains unverified.
        """
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise WorkspaceError("Invalid sandbox run ID.")
        self.engine._workspace(wid)
        run_dir = self.engine.evidence_root / wid / f"sandbox-{run_id}"
        result_file = run_dir / "result.json"
        if result_file.is_symlink() or getattr(result_file, "is_junction", lambda: False)():
            raise WorkspaceError("Sandbox result cannot be a link or junction.")
        if not result_file.is_file():
            return {"run_id": run_id, "status": "RUNNING_OR_NOT_STARTED",
                    "note": "No guest result is available yet."}
        if result_file.stat().st_size > 4 * 1024 * 1024:
            raise WorkspaceError("Sandbox result exceeds the 4 MB evidence limit.")
        try:
            raw = result_file.read_bytes()
            result = json.loads(raw.decode("utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WorkspaceError(f"Sandbox result is unreadable: {exc}") from exc
        if not isinstance(result, dict):
            raise WorkspaceError("Sandbox result must be a JSON object.")
        if result.get("id") != run_id:
            raise WorkspaceError("Sandbox result run ID does not match the requested run.")
        control = self.engine.root / "sandbox-control" / run_id / "config.json"
        try:
            cfg = json.loads(control.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkspaceError("Host run configuration is missing or invalid.") from exc
        if cfg.get("workspace") != wid or result.get("check") != cfg.get("check"):
            raise WorkspaceError("Sandbox result identity does not match host run configuration.")
        if result.get("status") not in {"PASS", "FAIL", "TIMEOUT", "ERROR"}:
            raise WorkspaceError("Sandbox result has an invalid status.")
        code = result.get("exit_code")
        if code is not None and (not isinstance(code, int) or isinstance(code, bool) or not -255 <= code <= 255):
            raise WorkspaceError("Sandbox result exit code is invalid.")
        if result["status"] == "PASS" and code != 0:
            raise WorkspaceError("PASS status is inconsistent with the exit code.")
        if result["status"] == "FAIL" and (code is None or code == 0):
            raise WorkspaceError("FAIL status is inconsistent with the exit code.")
        duration = result.get("duration_seconds")
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or not 0 <= duration <= 3600:
            raise WorkspaceError("Sandbox result duration is invalid.")
        for field in ("stdout", "stderr"):
            if not isinstance(result.get(field), str) or len(result[field]) > 30000:
                raise WorkspaceError(f"Sandbox {field} is missing or exceeds the output limit.")
        completed = result.get("completed_at")
        if not isinstance(completed, str):
            raise WorkspaceError("Sandbox completion timestamp is missing.")
        try:
            from datetime import datetime
            datetime.fromisoformat(completed.replace("Z", "+00:00"))
        except ValueError as exc:
            raise WorkspaceError("Sandbox completion timestamp is invalid.") from exc

        evidence = {"schema_version": 1, "workspace": wid, "sandbox_run_id": run_id,
                    "check": result["check"], "status": result["status"],
                    "exit_code": code, "duration_seconds": duration,
                    "stdout": result["stdout"], "stderr": result["stderr"],
                    "completed_at": completed, "guest": result.get("guest", "unknown"),
                    "sandboxed": True, "evidence_trust": "guest_report_unverified",
                    "verification": {"schema_valid": True, "identity_bound": True,
                                     "host_snapshot_sha256": hashlib.sha256(raw).hexdigest(),
                                     "verified_at": time.time(),
                                     "limitations": "Guest-controlled output is not cryptographic proof of execution."}}
        evidence_file = self.engine.evidence_root / wid / f"{run_id}.json"
        # Exclusive creation prevents silently replacing a previously captured
        # host snapshot with a later guest-authored result.
        try:
            with evidence_file.open("x", encoding="utf-8") as stream:
                json.dump(evidence, stream, indent=2)
        except FileExistsError:
            existing = json.loads(evidence_file.read_text(encoding="utf-8"))
            if existing.get("verification", {}).get("host_snapshot_sha256") != evidence["verification"]["host_snapshot_sha256"]:
                raise WorkspaceError("A different host evidence snapshot already exists for this run.")
            return existing
        self.engine._audit("sandbox_evidence_snapshotted", workspace=wid, run_id=run_id,
                           status=evidence["status"], sha256=evidence["verification"]["host_snapshot_sha256"])
        return evidence

    def read_result(self, wid: str, run_id: str) -> dict[str, Any]:
        return self.verify_result(wid, run_id)


def launch_approved_request(engine: DevWorkspace, request_file: str | Path) -> dict[str, Any]:
    """Dispatcher integration seam: launch only a request already approved by host UI.

    The approval dispatcher owns the approval record and UI. This helper only
    consumes its persisted decision and deliberately does not implement or
    modify approval policy.
    """
    candidate = Path(request_file)
    if candidate.is_symlink() or getattr(candidate, "is_junction", lambda: False)():
        raise WorkspaceError("Approval request cannot be a link or junction.")
    path = candidate.resolve()
    pending_root = (engine.root / "pending-check-approvals").resolve()
    if path.parent != pending_root or not re.fullmatch(r"[a-f0-9]{32}\.json", path.name):
        raise WorkspaceError("Approval request must be a canonical pending-check approval record.")
    try:
        request = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkspaceError(f"Approved check request is unreadable: {exc}") from exc
    if not isinstance(request, dict) or request.get("status") != "approved":
        raise WorkspaceError("Sandbox launch requires an explicit host-approved request.")
    if not re.fullmatch(r"[a-f0-9]{32}", str(request.get("id", ""))) or path.stem != request["id"]:
        raise WorkspaceError("Approved request ID is invalid or does not match its filename.")
    consumed = engine.root / "sandbox-consumed-approvals" / f"{request['id']}.json"
    consumed.parent.mkdir(parents=True, exist_ok=True)
    try:
        with consumed.open("x", encoding="utf-8") as stream:
            json.dump({"request_id": request["id"], "consumed_at": time.time()}, stream)
    except FileExistsError as exc:
        raise WorkspaceError("This host approval request has already been consumed.") from exc
    try:
        runner = WindowsSandboxRunner(engine)
        result = runner.launch(request["workspace"], request["check"], request.get("subdir", "."))
    except Exception:
        consumed.unlink(missing_ok=True)
        raise
    engine._audit("approved_sandbox_request_consumed", request_id=request["id"],
                  run_id=result["run_id"], workspace=request["workspace"])
    return {**result, "approval_request_id": request["id"]}
