from pathlib import Path
import ast


def test_mcp_adapter_uses_current_v2_lowlevel_api():
    source = Path(__file__).parents[1] / "atlas_dev_engine_mcp.py"
    text = source.read_text(encoding="utf-8")
    tree = ast.parse(text)
    names = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "handle_list_tools" in names
    assert "handle_call_tool" in names
    assert "main" in names
    assert "on_list_tools=handle_list_tools" in text
    assert "on_call_tool=handle_call_tool" in text
    assert "create_initialization_options()" in text
    assert "@server.list_tools()" not in text
    assert "@server.call_tool()" not in text
    assert "run_terminal_command" not in text
    assert "dev_request_check" in text
    assert "awaiting_host_approval" in text
    assert "is_error=True" in text


def test_mcp_adapter_declares_v2_sdk_requirement():
    requirement = (Path(__file__).parents[1] / "requirements-mcp.txt").read_text(encoding="utf-8")
    assert "mcp>=2.3,<3" in requirement
