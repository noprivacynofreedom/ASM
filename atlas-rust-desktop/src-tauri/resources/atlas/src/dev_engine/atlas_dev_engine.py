"""Isolated, auditable development workspaces for Atlas coding agents.

Agents may inspect and modify only a copied workspace outside the live repository.
There is intentionally no tool that applies changes to the live repository.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any

EXCLUDED_DIRS = {
    ".git", ".webview", ".atlas", "backups", "exports", "models",
    "node_modules", "target", "dist", "__pycache__", ".venv", "venv",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "coverage",
}
EXCLUDED_FILES = {
    "data.json", "settings.json", "settings.local.json",
}
EXCLUDED_SUFFIXES = {".gguf", ".safetensors", ".tmp", ".log", ".pyc", ".pem", ".key", ".p12", ".pfx"}
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 200 * 1024 * 1024
MAX_OUTPUT_CHARS = 30000
CHECKS = {
    "python_tests": ([sys.executable, "-m", "pytest", "-q"], 180),
    "python_compile": ([sys.executable, "-m", "compileall", "-q", "."], 90),
    "npm_build": (["npm", "run", "build"], 240),
    "npm_tests": (["npm", "test", "--", "--run"], 240),
    "cargo_check": (["cargo", "check", "--locked"], 300),
    "cargo_tests": (["cargo", "test", "--locked"], 300),
    "dotnet_test": (["dotnet", "test", "--nologo"], 300),
    "go_test": (["go", "test", "./..."], 300),
}

class WorkspaceError(RuntimeError):
    pass

def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def _is_link_or_junction(path: Path) -> bool:
    """Detect symlinks and Windows reparse-point directories before resolving.

    pathlib.is_symlink() alone does not identify every Windows junction. The
    reparse-point attribute check keeps workspace containment checks portable.
    """
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        if callable(is_junction) and is_junction():
            return True
        attrs = getattr(path.lstat(), "st_file_attributes", 0)
        return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    except (FileNotFoundError, NotADirectoryError, OSError):
        return False


def _safe_rel(value: str) -> Path:
    raw = str(value or "").replace("\\", "/")
    p = Path(raw)
    if not raw or p.is_absolute() or any(part in ("", ".", "..") for part in raw.split("/")):
        raise WorkspaceError("Use a relative path inside the isolated workspace.")
    if re.match(r"^[A-Za-z]:", raw):
        raise WorkspaceError("Absolute paths are not allowed.")
    return p

class DevWorkspace:
    def __init__(self, repo_root: str | Path | None = None, workspace_root: str | Path | None = None):
        self.repo = Path(repo_root or Path(__file__).resolve().parent).resolve()
        if not self.repo.is_dir():
            raise WorkspaceError("Atlas project root is unavailable.")
        home = os.environ.get("ATLAS_DEV_ENGINE_HOME")
        default = Path(home) / "DevWorkspaces" if home else Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local")) / "Atlas" / "DevWorkspaces"
        self.root = Path(workspace_root or default / self.repo.name).resolve()
        # Keep disposable workspaces, audit logs and exports completely outside
        # the selected source tree. A root nested in the repo would be copied
        # into itself by os.walk; a parent root would mix source and workspace
        # state under one trust boundary.
        if self.root == self.repo or self.root in self.repo.parents or self.repo in self.root.parents:
            raise WorkspaceError("Workspace storage must be outside and separate from the source project.")
        self.root.mkdir(parents=True, exist_ok=True)
        self.audit_path = self.root / "audit.jsonl"
        self.evidence_root = self.root / "evidence"
        self.metadata_root = self.root / "metadata"
        self.evidence_root.mkdir(parents=True, exist_ok=True)
        self.metadata_root.mkdir(parents=True, exist_ok=True)

    def _assert_workspace_tree_safe(self, ws: Path) -> None:
        """Fail closed if an agent-created link/junction exists anywhere in a workspace."""
        for current, dirs, files in os.walk(ws, topdown=True, followlinks=False):
            base = Path(current)
            unsafe = [name for name in dirs + files if _is_link_or_junction(base / name)]
            if unsafe:
                raise WorkspaceError(
                    "Workspace contains symbolic links or junctions; checks and handoff are blocked."
                )
            # Do not recurse into a reparse point even if the platform's walker
            # unexpectedly reports one as a directory.
            dirs[:] = [name for name in dirs if not _is_link_or_junction(base / name)]

    def _audit(self, action: str, **data: Any) -> None:
        event = {"time": time.time(), "action": action, **data}
        with self.audit_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def _workspace(self, wid: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{12}", str(wid)):
            raise WorkspaceError("Invalid workspace ID.")
        lexical = self.root / wid
        if _is_link_or_junction(lexical):
            raise WorkspaceError("Workspace root cannot be a symbolic link or junction.")
        path = lexical.resolve()
        if path.parent != self.root or not path.is_dir():
            raise WorkspaceError("Workspace does not exist.")
        # The canonical baseline is stored outside the agent-editable workspace.
        # The in-workspace marker is only a mirror and must remain byte-identical.
        canonical = self.metadata_root / f"{wid}.json"
        marker = path / ".atlas-workspace.json"
        if _is_link_or_junction(marker) or not canonical.is_file() or not marker.is_file():
            raise WorkspaceError("Workspace integrity metadata is missing or unsafe.")
        try:
            if marker.read_bytes() != canonical.read_bytes():
                raise WorkspaceError("Workspace integrity metadata was modified.")
        except OSError as exc:
            raise WorkspaceError("Workspace integrity metadata cannot be verified.") from exc
        return path

    def create(self, label: str = "agent-task") -> dict[str, Any]:
        wid = uuid.uuid4().hex[:12]
        dest = self.root / wid
        dest.mkdir(parents=False, exist_ok=False)
        manifest: dict[str, str] = {}
        total = 0
        copied = 0
        for current, dirs, files in os.walk(self.repo, topdown=True, followlinks=False):
            cur = Path(current)
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS and not _is_link_or_junction(cur / d)]
            rel_dir = cur.relative_to(self.repo)
            out_dir = dest / rel_dir
            out_dir.mkdir(parents=True, exist_ok=True)
            for filename in files:
                src = cur / filename
                if (_is_link_or_junction(src) or filename in EXCLUDED_FILES or filename.lower().startswith(".env")
                        or src.suffix.lower() in EXCLUDED_SUFFIXES):
                    continue
                try:
                    size = src.stat().st_size
                    if size > MAX_FILE_BYTES or total + size > MAX_TOTAL_BYTES:
                        continue
                    rel = src.relative_to(self.repo)
                    target = dest / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, target)
                    digest = _sha(target)
                    manifest[rel.as_posix()] = digest
                    total += size
                    copied += 1
                except (OSError, PermissionError):
                    continue
        meta = {
            "id": wid, "label": re.sub(r"[^a-zA-Z0-9 _.-]", "", str(label))[:80] or "agent-task",
            "created": time.time(), "source_root": str(self.repo),
            "source_head": self._git_read(["rev-parse", "HEAD"]),
            "source_branch": self._git_read(["branch", "--show-current"]),
            "manifest": manifest, "copy_count": copied, "bytes": total,
        }
        metadata_bytes = json.dumps(meta, indent=2).encode("utf-8")
        # Keep the authoritative baseline outside the workspace that agents edit.
        canonical_meta = self.metadata_root / f"{wid}.json"
        canonical_meta.write_bytes(metadata_bytes)
        (dest / ".atlas-workspace.json").write_bytes(metadata_bytes)
        self._audit("workspace_created", workspace=wid, label=meta["label"], source_root=str(self.repo),
                    files=copied, bytes=total, source_head=meta["source_head"], source_branch=meta["source_branch"])
        return {"workspace": wid, "label": meta["label"], "files": copied, "bytes": total,
                "source_branch": meta["source_branch"], "source_head": meta["source_head"],
                "location": str(dest), "excluded": sorted(EXCLUDED_DIRS | EXCLUDED_FILES)}

    def _git_read(self, args: list[str]) -> str | None:
        try:
            r = subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True,
                               timeout=5, shell=False)
            return r.stdout.strip() if r.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            return None

    def list_files(self, wid: str, limit: int = 500) -> list[str]:
        ws = self._workspace(wid)
        rows = []
        for p in ws.rglob("*"):
            if p.is_file() and p.name != ".atlas-workspace.json" and not _is_link_or_junction(p):
                rows.append(p.relative_to(ws).as_posix())
                if len(rows) >= min(max(int(limit), 1), 1000):
                    break
        return sorted(rows)

    def _file(self, wid: str, rel: str) -> Path:
        ws = self._workspace(wid)
        p = _safe_rel(rel)
        if p.as_posix() == ".atlas-workspace.json":
            raise WorkspaceError("Workspace integrity metadata is read-only.")
        # Reject symlinks and junctions in every existing path component before resolving.
        # Checking target.is_symlink() after resolve is ineffective because
        # resolve() has already followed the link.
        lexical = ws
        for part in p.parts:
            lexical = lexical / part
            if _is_link_or_junction(lexical):
                raise WorkspaceError("Symbolic links and junctions are not accessible.")
        target = lexical.resolve()
        if target == ws or ws not in target.parents:
            raise WorkspaceError("Path escapes the workspace.")
        return target

    def read_file(self, wid: str, rel: str) -> str:
        target = self._file(wid, rel)
        if not target.is_file():
            raise WorkspaceError("File not found.")
        if target.stat().st_size > MAX_FILE_BYTES:
            raise WorkspaceError("File exceeds the 2 MB read limit.")
        try:
            value = target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceError("Binary or non-UTF8 files cannot be read as text.") from exc
        self._audit("file_read", workspace=wid, path=str(rel))
        return value

    def write_file(self, wid: str, rel: str, content: str) -> dict[str, Any]:
        target = self._file(wid, rel)
        data = str(content).encode("utf-8")
        if len(data) > MAX_FILE_BYTES:
            raise WorkspaceError("File writes are limited to 2 MB.")
        if target.exists() and not target.is_file():
            raise WorkspaceError("Target is not a regular file.")
        target.parent.mkdir(parents=True, exist_ok=True)
        # Atomic replace inside the isolated workspace only.
        tmp = target.with_name(target.name + ".atlas-write-tmp")
        tmp.write_bytes(data)
        os.replace(tmp, target)
        self._audit("workspace_file_written", workspace=wid, path=str(rel), bytes=len(data))
        return {"written": str(rel), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                "live_repository_changed": False}

    def run_check(self, wid: str, check: str, subdir: str = ".") -> dict[str, Any]:
        ws = self._workspace(wid)
        self._assert_workspace_tree_safe(ws)
        if check not in CHECKS:
            raise WorkspaceError(f"Check not allowed. Choose one of: {', '.join(sorted(CHECKS))}")
        rel = Path(".") if subdir in ("", ".") else _safe_rel(subdir)
        lexical_cwd = ws
        for part in (() if str(rel) == "." else rel.parts):
            lexical_cwd = lexical_cwd / part
            if _is_link_or_junction(lexical_cwd):
                raise WorkspaceError("Check directories cannot contain symbolic links or junctions.")
        cwd = lexical_cwd.resolve()
        if ws != cwd and ws not in cwd.parents:
            raise WorkspaceError("Check directory escapes workspace.")
        if not cwd.is_dir():
            raise WorkspaceError("Check directory does not exist.")
        command, timeout = CHECKS[check]
        # Do not invoke a shell; command is selected from a fixed allowlist.
        if check == "npm_build" and not (cwd / "package.json").is_file():
            raise WorkspaceError("No package.json in the selected directory.")
        if check in ("cargo_check", "cargo_tests") and not (cwd / "Cargo.toml").is_file():
            raise WorkspaceError("No Cargo.toml in the selected directory.")
        if check in ("npm_build", "npm_tests") and not (cwd / "package.json").is_file():
            raise WorkspaceError("No package.json in the selected directory.")
        if check == "dotnet_test" and not any(cwd.glob("*.sln")) and not any(cwd.glob("*.csproj")):
            raise WorkspaceError("No .sln or .csproj file in the selected directory.")
        if check == "go_test" and not (cwd / "go.mod").is_file():
            raise WorkspaceError("No go.mod in the selected directory.")
        if check == "python_tests" and not any(cwd.glob("test*.py")) and not (cwd / "tests").exists():
            raise WorkspaceError("No Python tests found in the selected directory.")
        started = time.time()
        try:
            p = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                               timeout=timeout, shell=False)
            result = {"check": check, "exit_code": p.returncode,
                      "stdout": p.stdout[-MAX_OUTPUT_CHARS:], "stderr": p.stderr[-MAX_OUTPUT_CHARS:],
                      "duration_seconds": round(time.time() - started, 2),
                      "status": "PASS" if p.returncode == 0 else "FAIL"}
        except subprocess.TimeoutExpired as exc:
            result = {"check": check, "status": "TIMEOUT", "duration_seconds": round(time.time()-started,2),
                      "stdout": str(exc.stdout or "")[-MAX_OUTPUT_CHARS:],
                      "stderr": str(exc.stderr or "")[-MAX_OUTPUT_CHARS:]}
        result["workspace"] = wid
        result["evidence_id"] = uuid.uuid4().hex
        result["command"] = command
        result["working_directory"] = str(cwd)
        result["recorded_at"] = time.time()
        evidence_dir = self.evidence_root / wid
        evidence_dir.mkdir(parents=True, exist_ok=True)
        evidence_file = evidence_dir / f"{result['evidence_id']}.json"
        evidence_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["evidence_file"] = str(evidence_file)
        self._audit("check_run", workspace=wid, check=check, status=result["status"],
                    evidence_id=result["evidence_id"], exit_code=result.get("exit_code"))
        return result

    def diff(self, wid: str) -> dict[str, Any]:
        ws = self._workspace(wid)
        self._assert_workspace_tree_safe(ws)
        meta = json.loads((self.metadata_root / f"{wid}.json").read_text(encoding="utf-8"))
        baseline: dict[str, str] = meta["manifest"]
        current: dict[str, str] = {}
        for p in ws.rglob("*"):
            if not p.is_file() or p.name == ".atlas-workspace.json" or _is_link_or_junction(p):
                continue
            current[p.relative_to(ws).as_posix()] = _sha(p)
        added = sorted(set(current) - set(baseline))
        deleted = sorted(set(baseline) - set(current))
        modified = sorted(k for k in set(current) & set(baseline) if current[k] != baseline[k])
        return {"workspace": wid, "added": added, "modified": modified, "deleted": deleted,
                "changed_count": len(added)+len(modified)+len(deleted),
                "live_repository_changed": False,
                "evidence": [{"check": e.get("check"), "status": e.get("status"),
                              "exit_code": e.get("exit_code"), "evidence_id": e.get("evidence_id")}
                             for e in self.evidence(wid)],
                "note": "Changes are isolated. No live files or Git refs have been modified."}

    def delete_file(self, wid: str, rel: str) -> dict[str, Any]:
        """Delete a regular file inside the disposable workspace only."""
        target = self._file(wid, rel)
        if not target.exists() or not target.is_file():
            raise WorkspaceError("Only an existing regular file can be deleted.")
        target.unlink()
        self._audit("workspace_file_deleted", workspace=wid, path=str(rel))
        return {"deleted": str(rel), "workspace_only": True, "live_repository_changed": False}

    def evidence(self, wid: str) -> list[dict[str, Any]]:
        self._workspace(wid)
        folder = self.evidence_root / wid
        if not folder.exists():
            return []
        rows = []
        for p in sorted(folder.glob("*.json")):
            try:
                rows.append(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                rows.append({"evidence_file": p.name, "status": "UNREADABLE"})
        return rows

    def export_patch_bundle(self, wid: str) -> str:
        ws = self._workspace(wid)
        diff = self.diff(wid)
        out = self.root / f"atlas-agent-changes-{wid}.zip"
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("REVIEW-FIRST.json", json.dumps(diff, indent=2))
            for rel in diff["added"] + diff["modified"]:
                z.write(self._file(wid, rel), f"files/{rel}")
            meta = json.loads((self.metadata_root / f"{wid}.json").read_text(encoding="utf-8"))
            z.writestr("WORKSPACE-BASELINE.json", json.dumps({
                "workspace": wid, "source_root": meta.get("source_root"),
                "source_head": meta.get("source_head"), "source_branch": meta.get("source_branch"),
                "manifest": meta.get("manifest")
            }, indent=2))
            z.writestr("TEST-EVIDENCE.json", json.dumps(self.evidence(wid), ensure_ascii=False, indent=2))
            z.writestr("HANDOFF-README.txt", "Review-first Atlas agent handoff.\n\nFiles are under files/.\nDeleted files are listed in REVIEW-FIRST.json and are NOT applied automatically.\nTest evidence is included in TEST-EVIDENCE.json.\nNo changes have been applied to the source project.\n")
        self._audit("patch_bundle_exported", workspace=wid, path=str(out), changes=diff["changed_count"])
        return str(out)
