import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "atlas-rust-desktop" / "src-tauri" / "resources" / "atlas"))
import model_discovery as md


def touch(p, size=10):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)
    return p


class ModelDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runtime = self.root / "install" / "resources" / "atlas"
        self.data = self.root / "data"
        touch(self.runtime / "runtime" / "llama-vulkan" / "llama-server.exe")

    def tearDown(self):
        self.tmp.cleanup()

    def test_bundled_config_kept_when_its_models_exist(self):
        model = touch(self.root / "m" / "a.gguf")
        cfg = self.runtime / "runtime" / "llama-swap" / "config.yaml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(f'models:\n  "coder":\n    cmd: >\n      x.exe -m {model} -ngl 1\n')
        r = md.choose(self.runtime, self.data, cfg)
        self.assertEqual(r["mode"], "bundled")
        self.assertEqual(r["config"], str(cfg))

    def test_generates_config_when_bundled_models_are_missing(self):
        cfg = self.runtime / "runtime" / "llama-swap" / "config.yaml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text("models:\n  c:\n    cmd: >\n      x.exe -m F:\\nope\\a.gguf\n")
        touch(self.data / "models" / "qwen3-14b-Q5.gguf", 50)
        touch(self.data / "models" / "gemma-4-12b.gguf", 40)
        r = md.choose(self.runtime, self.data, cfg)
        self.assertEqual(r["mode"], "generated")
        text = Path(r["config"]).read_text()
        for role in md.ROLES:
            self.assertIn(role, text)
        self.assertIn("llama-server.exe", text)
        self.assertEqual(set(r["roles"]), set(md.ROLES))

    def test_one_model_serves_every_role(self):
        touch(self.data / "models" / "only.gguf")
        r = md.choose(self.runtime, self.data, None)
        self.assertEqual(r["mode"], "generated")
        self.assertEqual(len(set(r["roles"].values())), 1)
        self.assertEqual(set(r["roles"]), set(md.ROLES))

    def test_skips_mmproj_and_later_shards(self):
        d = self.data / "models"
        touch(d / "big-00001-of-00002.gguf", 30)
        touch(d / "big-00002-of-00002.gguf", 30)
        touch(d / "vision-mmproj-f16.gguf", 5)
        names = [p.name for p, _ in md.find_models([d])]
        self.assertEqual(names, ["big-00001-of-00002.gguf"])

    def test_path_with_space_is_quoted_with_forward_slashes(self):
        self.assertEqual(md.arg("F:\\My Models\\a.gguf"), '"F:/My Models/a.gguf"')
        self.assertEqual(md.arg("F:\\models\\a.gguf"), "F:/models/a.gguf")

    def test_generated_config_quotes_model_path_with_space(self):
        touch(self.data / "my models" / "only.gguf")
        r = md.choose(self.runtime, self.data, None, [str(self.data / "my models")])
        text = Path(r["config"]).read_text()
        self.assertIn('-m "', text)
        # The relative llama-server.exe path may use backslashes on Windows (the bundled config does too);
        # only the model path must be forward-slash.
        model_line = next(l for l in text.splitlines() if "-m " in l)
        self.assertNotIn("\\", model_line)

    def test_template_config_finds_models_folder_and_keeps_flags(self):
        cfg = self.runtime / "runtime" / "llama-swap" / "config.yaml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text('models:\n  "coder":\n    cmd: >\n      x.exe -m {models}/q/a.gguf -ngl 99 --n-cpu-moe 28\n')
        touch(self.data / "models" / "q" / "a.gguf")
        r = md.choose(self.runtime, self.data, cfg)
        self.assertEqual(r["mode"], "bundled-template")
        text = Path(r["config"]).read_text()
        self.assertNotIn("{models}", text)
        self.assertIn("--n-cpu-moe 28", text)
        self.assertIn("/models/q/a.gguf", text)

    def test_template_config_with_missing_files_falls_back_to_scan(self):
        cfg = self.runtime / "runtime" / "llama-swap" / "config.yaml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text('models:\n  "coder":\n    cmd: >\n      x.exe -m {models}/q/a.gguf\n')
        touch(self.data / "models" / "other.gguf")
        r = md.choose(self.runtime, self.data, cfg)
        self.assertEqual(r["mode"], "generated")

    def test_shipped_config_has_no_fixed_model_paths(self):
        shipped = Path(md.__file__).parent / "runtime" / "llama-swap" / "config.yaml"
        text = shipped.read_text(encoding="utf-8")
        self.assertNotRegex(text, r"-m\s+[A-Za-z]:")
        self.assertGreaterEqual(len(md.template_files(text)), 5)

    def test_no_models_reports_none(self):
        r = md.choose(self.runtime, self.data, None)
        self.assertEqual(r["mode"], "none")

    def test_env_models_dir_is_searched(self):
        import os
        touch(self.root / "elsewhere" / "z.gguf")
        os.environ["ATLAS_MODELS_DIR"] = str(self.root / "elsewhere")
        try:
            r = md.choose(self.runtime, self.data, None)
        finally:
            del os.environ["ATLAS_MODELS_DIR"]
        self.assertEqual(r["mode"], "generated")


if __name__ == "__main__":
    unittest.main()
