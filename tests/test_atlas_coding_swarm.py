import sys, tempfile, unittest
from pathlib import Path
import _paths
sys.path.insert(0, str(_paths.APP / "agents"))
import atlas_coding_swarm as swarm

class CodingSwarmSafetyTests(unittest.TestCase):
    def test_reject_absolute_path(self):
        with self.assertRaises(ValueError): swarm._validate_files([{"path":"/tmp/x","content":"x"}])
    def test_reject_parent_traversal(self):
        with self.assertRaises(ValueError): swarm._validate_files([{"path":"../x","content":"x"}])
    def test_reject_protected_directory(self):
        with self.assertRaises(ValueError): swarm._validate_files([{"path":".git/config","content":"x"}])
    def test_reject_duplicate_case_insensitive(self):
        with self.assertRaises(ValueError):
            swarm._validate_files([{"path":"A.py","content":"1"},{"path":"a.py","content":"2"}])
    def test_allowlist_only(self):
        with self.assertRaises(ValueError): swarm.run_allowed_tests(".", "powershell")
    def test_safe_write_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            result = swarm._write_files(Path(temp), "demo", "tsk_1234567890", [{"path":"src/main.py","content":"print(1)"}])
            self.assertTrue((Path(result["workspace"])/"src/main.py").is_file())
            self.assertTrue((Path(result["workspace"])/".atlas-swarm-manifest.json").is_file())

if __name__ == "__main__": unittest.main()
