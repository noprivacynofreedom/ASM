import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from atlas_dev_engine import DevWorkspace, WorkspaceError
from windows_sandbox import WindowsSandboxRunner


def make_engine(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "test_sample.py").write_text("def test_ok(): assert True\n")
    (repo / "package.json").write_text('{"scripts":{"build":"echo build"}}')
    return DevWorkspace(repo, tmp_path / "engine")


def test_prepare_and_wsb_isolates_workspace_and_disables_network_clipboard(tmp_path):
    engine = make_engine(tmp_path)
    ws = engine.create()
    runner = WindowsSandboxRunner(engine)
    prepared = runner.prepare(ws["workspace"], "python_tests")
    wsb = runner.build_wsb(prepared)
    root = ET.parse(wsb).getroot()
    assert root.findtext("Networking") == "Disable"
    assert root.findtext("Clipboard") == "Disable"
    assert root.findtext("VGpu") == "Disable"
    mappings = root.find("MappedFolders").findall("MappedFolder")
    assert len(mappings) == 3
    assert mappings[0].findtext("ReadOnly") == "true"  # runner/control
    assert mappings[1].findtext("ReadOnly") == "false"  # disposable workspace
    assert "C:\\AtlasWorkspace" in wsb.read_text()


def test_prepare_rejects_unknown_check_and_path_traversal(tmp_path):
    engine = make_engine(tmp_path)
    ws = engine.create()
    runner = WindowsSandboxRunner(engine)
    with pytest.raises(WorkspaceError, match="Unsupported"):
        runner.prepare(ws["workspace"], "arbitrary_shell")
    with pytest.raises(WorkspaceError, match="relative"):
        runner.prepare(ws["workspace"], "python_tests", "../outside")


def test_runner_control_config_contains_only_fixed_check_identity(tmp_path):
    engine = make_engine(tmp_path)
    ws = engine.create()
    runner = WindowsSandboxRunner(engine)
    prepared = runner.prepare(ws["workspace"], "python_tests")
    cfg = json.loads((Path(prepared["control_path"]) / "config.json").read_text())
    assert cfg["check"] == "python_tests"
    assert "command" not in cfg
    assert "args" not in cfg


def test_read_result_is_pending_until_guest_writes_result(tmp_path):
    engine = make_engine(tmp_path)
    ws = engine.create()
    runner = WindowsSandboxRunner(engine)
    prepared = runner.prepare(ws["workspace"], "python_tests")
    assert runner.read_result(ws["workspace"], prepared["run_id"])["status"] == "RUNNING_OR_NOT_STARTED"


def test_sandbox_uses_disposable_copy_not_live_workspace(tmp_path):
    engine = make_engine(tmp_path)
    ws = engine.create()
    live = Path(ws["path"]) if "path" in ws else engine._workspace(ws["workspace"])
    original = (live / "test_sample.py").read_text()
    runner = WindowsSandboxRunner(engine)
    prepared = runner.prepare(ws["workspace"], "python_tests")
    staged = Path(prepared["workspace_path"])
    assert staged != live
    assert (staged / "test_sample.py").read_text() == original
    (staged / "test_sample.py").write_text("tampered by guest")
    assert (live / "test_sample.py").read_text() == original


def test_verify_result_binds_identity_and_snapshots_host_evidence(tmp_path):
    engine = make_engine(tmp_path)
    ws = engine.create()
    runner = WindowsSandboxRunner(engine)
    prepared = runner.prepare(ws["workspace"], "python_tests")
    result = {
        "id": prepared["run_id"], "check": "python_tests", "status": "PASS",
        "exit_code": 0, "duration_seconds": 1.25, "stdout": "2 passed",
        "stderr": "", "guest": "Windows Sandbox", "completed_at": "2026-11-07T00:00:00+00:00"
    }
    result_path = Path(prepared["results_path"]) / "result.json"
    result_path.write_text(json.dumps(result))
    verified = runner.verify_result(ws["workspace"], prepared["run_id"])
    assert verified["verification"]["schema_valid"] is True
    assert verified["evidence_trust"] == "guest_report_unverified"
    assert len(verified["verification"]["host_snapshot_sha256"]) == 64
    assert runner.verify_result(ws["workspace"], prepared["run_id"]) == verified


def test_verify_result_rejects_forged_identity_and_inconsistent_pass(tmp_path):
    engine = make_engine(tmp_path)
    ws = engine.create()
    runner = WindowsSandboxRunner(engine)
    prepared = runner.prepare(ws["workspace"], "python_tests")
    result = {
        "id": prepared["run_id"], "check": "python_tests", "status": "PASS",
        "exit_code": 2, "duration_seconds": 1, "stdout": "", "stderr": "",
        "completed_at": "2026-11-07T00:00:00+00:00"
    }
    Path(prepared["results_path"], "result.json").write_text(json.dumps(result))
    with pytest.raises(WorkspaceError, match="inconsistent"):
        runner.verify_result(ws["workspace"], prepared["run_id"])


def test_dispatcher_seam_refuses_unapproved_requests(tmp_path):
    from windows_sandbox import launch_approved_request
    engine = make_engine(tmp_path)
    pending = engine.root / "pending-check-approvals"
    pending.mkdir()
    request = pending / ("a" * 32 + ".json")
    request.write_text(json.dumps({"id": "a" * 32, "workspace": "b" * 12,
                                   "check": "python_tests", "status": "awaiting_host_approval"}))
    with pytest.raises(WorkspaceError, match="explicit host-approved"):
        launch_approved_request(engine, request)


def test_dispatcher_seam_consumes_only_canonical_approved_record_once(tmp_path, monkeypatch):
    import windows_sandbox
    engine = make_engine(tmp_path)
    wid = engine.create()["workspace"]
    pending = engine.root / "pending-check-approvals"
    pending.mkdir()
    request_id = "c" * 32
    request = pending / f"{request_id}.json"
    request.write_text(json.dumps({"id": request_id, "workspace": wid,
                                   "check": "python_tests", "subdir": ".", "status": "approved"}))

    class FakeRunner:
        def __init__(self, engine):
            self.engine = engine
        def launch(self, workspace, check, subdir):
            return {"run_id": "d" * 32, "workspace": workspace, "check": check,
                    "subdir": subdir, "status": "launched_not_yet_completed"}

    monkeypatch.setattr(windows_sandbox, "WindowsSandboxRunner", FakeRunner)
    launched = windows_sandbox.launch_approved_request(engine, request)
    assert launched["approval_request_id"] == request_id
    with pytest.raises(WorkspaceError, match="already been consumed"):
        windows_sandbox.launch_approved_request(engine, request)
