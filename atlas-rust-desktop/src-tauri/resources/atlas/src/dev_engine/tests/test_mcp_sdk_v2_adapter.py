import asyncio
import contextlib
import importlib.util
import pathlib
import sys
import types as pytypes


class FakeTool:
    def __init__(self, **kwargs): self.__dict__.update(kwargs)


class FakeTextContent:
    def __init__(self, **kwargs): self.__dict__.update(kwargs)


class FakeListToolsResult:
    def __init__(self, **kwargs): self.__dict__.update(kwargs)


class FakeCallToolResult:
    def __init__(self, **kwargs): self.__dict__.update(kwargs)


class FakeCallToolRequestParams:
    def __init__(self, name, arguments=None):
        self.name, self.arguments = name, arguments or {}


class FakeServer:
    instance = None
    def __init__(self, name, *, version, on_list_tools, on_call_tool):
        self.name, self.version = name, version
        self.on_list_tools, self.on_call_tool = on_list_tools, on_call_tool
        self.run_args = None
        FakeServer.instance = self

    def create_initialization_options(self):
        return {"server_name": self.name, "server_version": self.version}

    async def run(self, read_stream, write_stream, options):
        self.run_args = (read_stream, write_stream, options)


@contextlib.asynccontextmanager
async def fake_stdio_server():
    yield "fake-read", "fake-write"


def load_adapter(monkeypatch, tmp_path):
    source_root = tmp_path / "approved-project"
    source_root.mkdir()
    (source_root / "main.py").write_text("print('hello')", encoding="utf-8")
    engine_home = tmp_path / "engine-home"
    monkeypatch.setenv("ATLAS_DEV_PROJECT_ROOT", str(source_root))
    monkeypatch.setenv("ATLAS_DEV_ENGINE_HOME", str(engine_home))

    mcp_pkg = pytypes.ModuleType("mcp")
    mcp_pkg.__path__ = []
    server_pkg = pytypes.ModuleType("mcp.server")
    server_pkg.__path__ = []
    server_pkg.Server = FakeServer
    stdio_mod = pytypes.ModuleType("mcp.server.stdio")
    stdio_mod.stdio_server = fake_stdio_server
    types_mod = pytypes.ModuleType("mcp.types")
    types_mod.Tool = FakeTool
    types_mod.TextContent = FakeTextContent
    types_mod.ListToolsResult = FakeListToolsResult
    types_mod.CallToolResult = FakeCallToolResult
    types_mod.CallToolRequestParams = FakeCallToolRequestParams

    monkeypatch.setitem(sys.modules, "mcp", mcp_pkg)
    monkeypatch.setitem(sys.modules, "mcp.server", server_pkg)
    monkeypatch.setitem(sys.modules, "mcp.server.stdio", stdio_mod)
    monkeypatch.setitem(sys.modules, "mcp.types", types_mod)

    path = pathlib.Path(__file__).parents[1] / "atlas_dev_engine_mcp.py"
    monkeypatch.syspath_prepend(str(path.parent))
    spec = importlib.util.spec_from_file_location("atlas_dev_engine_mcp_tested", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v2_server_constructor_tool_registration_and_stdio_entrypoint(monkeypatch, tmp_path):
    module = load_adapter(monkeypatch, tmp_path)
    server = FakeServer.instance
    assert server.name == "atlas-dev-engine"
    assert server.version == "1.2.0"
    assert callable(server.on_list_tools)
    assert callable(server.on_call_tool)

    listed = asyncio.run(server.on_list_tools(None, None))
    assert len(listed.tools) == 12
    assert all(isinstance(t, FakeTool) and "input_schema" in t.__dict__ for t in listed.tools)

    asyncio.run(module.main())
    assert server.run_args == ("fake-read", "fake-write",
                               {"server_name": "atlas-dev-engine", "server_version": "1.2.0"})


def test_v2_tool_dispatch_returns_success_and_mcp_error_result(monkeypatch, tmp_path):
    module = load_adapter(monkeypatch, tmp_path)
    success = asyncio.run(module.handle_call_tool(
        None, FakeCallToolRequestParams("dev_create_workspace", {"label": "mcp-test"})))
    assert success.is_error is False
    assert '"workspace"' in success.content[0].text

    failure = asyncio.run(module.handle_call_tool(
        None, FakeCallToolRequestParams("not_a_tool", {})))
    assert failure.is_error is True
    assert "Unknown tool" in failure.content[0].text
