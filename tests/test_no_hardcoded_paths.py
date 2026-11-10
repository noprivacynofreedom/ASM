"""Shipped Python code must not default to one developer's F:\\ drive."""
import json
import tempfile
import unittest
from pathlib import Path

import _paths  # noqa: F401  (puts the shipped backend on sys.path)
import config
import server


class DefaultsTests(unittest.TestCase):
    def test_server_defaults_have_no_drive_paths(self):
        self.assertEqual(server.DEFAULTS["llama_swap_exe"], "")
        self.assertEqual(server.DEFAULTS["llama_swap_config"], "")

    def test_config_defaults_have_no_drive_paths(self):
        self.assertEqual(config._DEFAULTS["llama_swap_exe"], "")
        self.assertEqual(config._DEFAULTS["llama_swap_config"], "")

    def test_missing_settings_file_gives_empty_paths(self):
        with tempfile.TemporaryDirectory() as d:
            s = server.load_settings(str(Path(d) / "none.json"))
        self.assertEqual(s["llama_swap_exe"], "")

    def test_user_settings_still_override(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.json"
            p.write_text(json.dumps({"llama_swap_exe": "C:\\x\\ls.exe"}), encoding="utf-8")
            self.assertEqual(server.load_settings(str(p))["llama_swap_exe"], "C:\\x\\ls.exe")

    def test_shipped_python_has_no_f_drive_default(self):
        app = Path(_paths.APP)
        for name in ("config.py", "server.py", "app.py"):
            text = (app / name).read_text(encoding="utf-8")
            self.assertNotIn("f:\\app-dev", text.lower(), name)


if __name__ == "__main__":
    unittest.main()
