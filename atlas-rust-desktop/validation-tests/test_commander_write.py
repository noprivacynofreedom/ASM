"""write_file / write_project_file: create-only by default, stay inside root, refuse protected paths."""
import importlib.util, os, pathlib, tempfile, unittest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src-tauri" / "resources" / "atlas" / "src" / "mcp_commander.py"


def load(root, readonly=""):
    os.environ["ATLAS_WORKSPACE"] = str(root)
    os.environ["ATLAS_COMMANDER_READONLY"] = readonly
    spec = importlib.util.spec_from_file_location("cmd_under_test", SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class WriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name).resolve()
        self.m = load(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_both_names_create_file_and_folders(self):
        for name, rel in (("write_file", "a/b.txt"), ("write_project_file", "c.txt")):
            out = self.m.call_tool(name, {"path": rel, "content": "héllo"})
            self.assertTrue(out["created"])
            self.assertEqual((self.root / rel).read_text(encoding="utf-8"), "héllo")

    def test_existing_file_needs_overwrite(self):
        self.m.call_tool("write_file", {"path": "x.txt", "content": "1"})
        with self.assertRaises(ValueError):
            self.m.call_tool("write_file", {"path": "x.txt", "content": "2"})
        out = self.m.call_tool("write_file", {"path": "x.txt", "content": "2", "overwrite": True})
        self.assertTrue(out["overwritten"])
        self.assertEqual((self.root / "x.txt").read_text(), "2")
        self.assertFalse(list(self.root.glob("*.atlas-tmp")))

    def test_refuses_outside_secret_and_git(self):
        for bad in ("../evil.txt", ".env", ".git/config", "node_modules/x.js", "k.pem", "."):
            with self.assertRaises(ValueError, msg=bad):
                self.m.call_tool("write_file", {"path": bad, "content": "x"})

    def test_bad_arguments_and_size(self):
        with self.assertRaises(ValueError):
            self.m.call_tool("write_file", {"path": "x.txt"})
        with self.assertRaises(ValueError):
            self.m.call_tool("write_file", {"path": "x.txt", "content": "a" * (self.m.MAX_WRITE_BYTES + 1)})

    def test_readonly_switch_hides_and_blocks(self):
        m = load(self.root, "1")
        self.assertFalse([t for t in m.tool_definitions() if t["name"] in m.WRITE_TOOLS])
        with self.assertRaises(ValueError):
            m.call_tool("write_file", {"path": "x.txt", "content": "x"})

    def test_tools_listed_and_json_rpc(self):
        names = {t["name"] for t in self.m.tool_definitions()}
        self.assertTrue({"write_file", "write_project_file"} <= names)


class WebSearchTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        for k in ("ATLAS_BRAVE_API_KEY", "ATLAS_SEARXNG_URL", "ATLAS_COMMANDER_OFFLINE"):
            os.environ.pop(k, None)
        self.m = load(pathlib.Path(self.d.name))

    def tearDown(self):
        os.environ.pop("ATLAS_COMMANDER_OFFLINE", None)
        self.d.cleanup()

    def test_parse_brave_and_searxng(self):
        brave = {"web": {"results": [{"title": "A <b>x</b>", "url": "https://a.test", "description": "d &amp; e"}]}}
        searx = {"results": [{"title": "B", "url": "https://b.test", "content": "c"}]}
        self.assertEqual(self.m.parse_search_results(brave, 5), [{"title": "A x", "url": "https://a.test", "snippet": "d & e"}])
        self.assertEqual(self.m.parse_search_results(searx, 5)[0]["snippet"], "c")

    def test_not_configured_and_empty_query(self):
        with self.assertRaises(ValueError) as ctx:
            self.m.call_tool("web_search", {"query": "x"})
        self.assertIn("ATLAS_BRAVE_API_KEY", str(ctx.exception))
        with self.assertRaises(ValueError):
            self.m.call_tool("web_search", {"query": " "})

    def test_offline_switch(self):
        os.environ["ATLAS_COMMANDER_OFFLINE"] = "1"
        self.assertFalse([t for t in self.m.tool_definitions() if t["name"] == "web_search"])
        with self.assertRaises(ValueError):
            self.m.call_tool("web_search", {"query": "x"})


if __name__ == "__main__":
    unittest.main()
