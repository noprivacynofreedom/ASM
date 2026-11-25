"""config.py (used by llm.py, so by every swarm worker) must read the same settings.json as server.py.

Bug found 2026-11-18: config.py read <install>/settings.json, which does not exist, so swarm workers
always called llama-swap on the default port 8080 and ignored upstream_port in the data folder.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "src-tauri" / "resources" / "atlas"


class ConfigFollowsDataDir(unittest.TestCase):
    def test_upstream_port_comes_from_atlas_data_dir(self):
        with tempfile.TemporaryDirectory() as data:
            Path(data, "settings.json").write_text(json.dumps({"upstream_port": 18999, "llm_model": "e2e-model"}), encoding="utf-8")
            out = subprocess.run([sys.executable, "-c", "import config; print(config.SETTINGS['upstream_port'], config.SETTINGS['llm_model'])"],
                                 cwd=APP, env={**os.environ, "ATLAS_DATA_DIR": data}, capture_output=True, text=True, timeout=30)
            self.assertEqual(out.stdout.split(), ["18999", "e2e-model"], out.stderr)


if __name__ == "__main__":
    unittest.main()
