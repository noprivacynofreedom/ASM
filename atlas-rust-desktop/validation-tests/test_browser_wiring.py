"""Browser MCP wiring: built-in 'browser' server in server.py, the Browser control in index.html,
screenshot rendering, and the installer bundle. No real browser needed."""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ATLAS = ROOT / "atlas-rust-desktop" / "src-tauri" / "resources" / "atlas"
HTML = (ATLAS / "index.html").read_text(encoding="utf-8")


def server_probe(code, settings=None):
    """Import server.py in a throwaway data folder and run code; returns its JSON output."""
    with tempfile.TemporaryDirectory(prefix="atlas-browser-wiring-") as tmp:
        if settings is not None:
            Path(tmp, "settings.json").write_text(json.dumps(settings), encoding="utf-8")
        env = dict(os.environ, ATLAS_DATA_DIR=tmp, ATLAS_OBSERVABILITY_DB=str(Path(tmp, "o.sqlite3")),
                   ATLAS_RUNTIME_ROOT=str(ATLAS), PYTHONDONTWRITEBYTECODE="1")
        run = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, '.'); import server, json\n" + code],
                             cwd=ATLAS, env=env, capture_output=True, text=True, timeout=120)
        if run.returncode != 0:
            raise AssertionError(run.stderr[-1500:])
        return json.loads(run.stdout.strip().splitlines()[-1])


class BuiltInServer(unittest.TestCase):
    def test_default_registers_browser_with_auto_mode(self):
        specs = server_probe("print(json.dumps(server._mcp_specs()))")
        browser = [s for s in specs if s["name"] == "browser"]
        self.assertEqual(len(browser), 1)
        self.assertTrue(browser[0]["command"][-1].endswith("browser_mcp.py"))
        self.assertTrue(Path(browser[0]["command"][-1]).is_file())
        self.assertEqual(browser[0]["env"]["ATLAS_BROWSER_MODE"], "auto")

    def test_mode_passed_and_user_servers_kept(self):
        mine = {"name": "mine", "command": ["{python}", "x.py"]}
        specs = server_probe("print(json.dumps(server._mcp_specs()))",
                             {"browser_mode": "sandbox", "mcp_servers": [mine]})
        names = [s["name"] for s in specs]
        self.assertIn("mine", names)
        self.assertEqual(next(s for s in specs if s["name"] == "browser")["env"]["ATLAS_BROWSER_MODE"], "sandbox")

    def test_off_removes_it_and_user_entry_wins(self):
        off = server_probe("print(json.dumps([s['name'] for s in server._mcp_specs()]))", {"browser_enabled": False})
        self.assertNotIn("browser", off)
        own = {"name": "browser", "command": ["{python}", "mine.py"]}
        specs = server_probe("print(json.dumps(server._mcp_specs()))", {"mcp_servers": [own]})
        browsers = [s for s in specs if s["name"] == "browser"]
        self.assertEqual(len(browsers), 1)
        self.assertTrue(browsers[0]["command"][-1].endswith("mine.py"))

    def test_bad_mode_falls_back_and_set_browser_validates(self):
        out = server_probe(
            "r={}\n"
            "try: server._set_browser({'mode':'nope'})\n"
            "except ValueError as e: r['err']=str(e)\n"
            "try: server._set_browser({'enabled':'yes'})\n"
            "except ValueError as e: r['err2']=str(e)\n"
            "r['saved']=server._set_browser({'mode':'host','enabled':False})\n"
            "r['names']=[s['name'] for s in server._mcp_specs()]\n"
            "r['mode_in_file']=json.load(open(server.SETTINGS_PATH))['browser_mode']\n"
            "server._MCP.stop_all()\nprint(json.dumps(r))")
        self.assertIn("auto, sandbox or host", out["err"])
        self.assertIn("err2", out)
        self.assertEqual(out["saved"], {"mode": "host", "enabled": False})
        self.assertNotIn("browser", out["names"])
        self.assertEqual(out["mode_in_file"], "host")


class Ui(unittest.TestCase):
    def test_control_and_keyboard_access(self):
        self.assertIn('id="brBtn" type="button"', HTML)
        self.assertIn('<dialog id="brDlg" aria-labelledby="brTitle">', HTML)
        self.assertIn('id="brOn"', HTML)
        for mode in ("auto", "sandbox", "host"):
            self.assertIn(f'<option value="{mode}">', HTML)
        self.assertIn("#brBtn:focus-visible", HTML)
        self.assertIn("/api/browser", HTML)

    def test_new_blocks_cannot_push_the_page(self):
        css = re.search(r"(?m)^#brDlg(?:,#ghDlg)?\{([^}]*)\}", HTML).group(1)
        self.assertIn("max-height", css)
        self.assertIn("overflow:auto", css)
        self.assertIn("flex:none", re.search(r"(?m)^#brBtn(?:,#\w+)*\{([^}]*)\}", HTML).group(1))
        shots = re.search(r"(?m)^\.exec-shots\{([^}]*)\}", HTML).group(1)
        self.assertIn("max-height", shots)
        self.assertIn("overflow:auto", shots)
        self.assertIn("max-width:100%", re.search(r"(?m)^\.exec-shots img\{([^}]*)\}", HTML).group(1))
        self.assertRegex(HTML, r"@media \(max-width:600px\)\{#brDlg")

    def test_screenshots_render_as_images_without_base64_text(self):
        self.assertIn("function execImages(", HTML)
        self.assertIn("function execStripImages(", HTML)
        self.assertIn('img.alt = `Browser screenshot', HTML)
        self.assertIn("[image shown above]", HTML)
        self.assertIn('/^image\\/(png|jpeg|webp|gif)$/', HTML)  # only real image types become data: URLs
        self.assertIn('pics += toolImgs.map', HTML)  # chat log tool screenshot rendering
        self.assertIn('pics += receipt.images.filter', HTML)  # message image attachment rendering


class Bundle(unittest.TestCase):
    def test_script_ships_and_is_not_core_compiled(self):
        self.assertTrue((ATLAS / "browser_mcp.py").is_file())
        core = (ROOT / "core-files.txt").read_text(encoding="utf-8")
        self.assertNotIn("browser_mcp", core)  # launched as a script, so it must stay a plain .py

    def test_tauri_ships_the_whole_atlas_folder(self):
        conf = json.loads((ROOT / "atlas-rust-desktop" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
        self.assertEqual(conf["bundle"]["resources"].get("resources/atlas"), "atlas")

    def test_playwright_in_bundled_requirements(self):
        reqs = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
        self.assertRegex(reqs, r"(?m)^playwright")

    def test_check_bundle_requires_browser_script(self):
        text = (ROOT / "check-bundle.py").read_text(encoding="utf-8")
        self.assertIn("browser_mcp.py", text)


if __name__ == "__main__":
    unittest.main()
