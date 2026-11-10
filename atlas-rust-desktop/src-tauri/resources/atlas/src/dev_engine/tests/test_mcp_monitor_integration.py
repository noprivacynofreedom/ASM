import json
import os
import pathlib
import sys
import textwrap
import time

from mcp_monitor import MCPMonitor, resolve_mcp_server_specs


def test_resolve_specs_expands_command_cwd_and_child_environment(tmp_path):
    project = tmp_path / "Atlas"
    project.mkdir()
    raw = [{
        "name": "Dev Engine",
        "enabled": True,
        "command": ["{python}", "{project}/src/dev_engine/server.py"],
        "cwd": "{project}/src/dev_engine",
        "env": {
            "ATLAS_DEV_PROJECT_ROOT": "D:\\\\Approved\\\\Project",
            "ATLAS_DEV_ENGINE_HOME": "%LOCALAPPDATA%\\\\Atlas\\\\DevEngine",
        },
    }, {"name": "disabled", "enabled": False, "command": ["ignore"]}]
    specs = resolve_mcp_server_specs(raw, project, sys.executable,
                                      {"LOCALAPPDATA": "C:\\\\Users\\\\Test\\\\AppData\\\\Local"})
    assert len(specs) == 1
    assert specs[0]["command"] == [sys.executable, str(project / "src/dev_engine/server.py")]
    assert specs[0]["cwd"] == str(project / "src/dev_engine")
    assert specs[0]["env"]["ATLAS_DEV_PROJECT_ROOT"] == "D:\\\\Approved\\\\Project"
    assert specs[0]["env"]["ATLAS_DEV_ENGINE_HOME"] == "C:\\\\Users\\\\Test\\\\AppData\\\\Local\\\\Atlas\\\\DevEngine"


def test_monitor_stdio_handshake_tool_registration_call_and_env(tmp_path):
    fake = tmp_path / "fake_mcp_server.py"
    fake.write_text(textwrap.dedent("""
        import json, os, sys
        for line in sys.stdin:
            try:
                req = json.loads(line)
            except Exception:
                continue
            method = req.get("method")
            if method == "notifications/initialized":
                continue
            rid = req.get("id")
            if rid is None:
                continue
            if method == "initialize":
                result = {"protocolVersion": req["params"]["protocolVersion"],
                          "capabilities": {"tools": {"listChanged": False}},
                          "serverInfo": {"name": "fake-atlas", "version": "1.0"}}
            elif method == "tools/list":
                result = {"tools": [
                    {"name": "env_probe", "description": "Return child env",
                     "inputSchema": {"type": "object", "properties": {}}},
                    {"name": "fail_probe", "description": "Return tool error",
                     "inputSchema": {"type": "object", "properties": {}}}
                ]}
            elif method == "tools/call":
                name = req["params"]["name"]
                if name == "env_probe":
                    result = {"content": [{"type": "text", "text": "ok"}],
                              "structuredContent": {"verified": True,
                                  "env": os.environ.get("ATLAS_TEST_ENV")},
                              "isError": False}
                else:
                    result = {"content": [{"type": "text", "text": "expected failure"}],
                              "isError": True}
            else:
                result = {}
            sys.stdout.write(json.dumps({"jsonrpc":"2.0","id":rid,"result":result}) + "\\n")
            sys.stdout.flush()
    """), encoding="utf-8")
    monitor = MCPMonitor([{
        "name": "fake",
        "command": [sys.executable, str(fake)],
        "cwd": str(tmp_path),
        "env": {"ATLAS_TEST_ENV": "passed-through"},
    }])
    status = monitor.check_all()
    row = status["servers"][0]
    assert row["state"] == "online"
    assert row["process_running"] is True
    assert {t["name"] for t in row["tools"]} == {"env_probe", "fail_probe"}

    success = monitor.call_tool("fake", "env_probe", {})
    assert success["status"] == "VERIFIED"
    assert success["result"]["structuredContent"]["env"] == "passed-through"

    failure = None
    try:
        monitor.call_tool("fake", "fail_probe", {})
    except Exception as exc:
        failure = exc
    # isError is represented as evidence, not raised by the monitor.
    assert failure is None
    assert monitor.status()["servers"][0]["last_execution"]["status"] == "FAILED"

    monitor.stop_all()
    assert monitor.status()["servers"][0]["process_running"] is False



def test_monitor_stops_owned_child_after_failed_handshake(tmp_path):
    fake = tmp_path / "exits_without_handshake.py"
    fake.write_text("import sys\\nsys.stdin.readline()\\n", encoding="utf-8")
    monitor = MCPMonitor([{
        "name": "broken",
        "command": [sys.executable, str(fake)],
        "cwd": str(tmp_path),
    }])
    row = monitor.check_all()["servers"][0]
    assert row["state"] == "error"
    assert row["process_running"] is False
    assert row["pid"] is None
    assert "closed stdout" in row["error"]
