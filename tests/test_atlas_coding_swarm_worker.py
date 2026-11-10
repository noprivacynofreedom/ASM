import importlib.util
import tempfile
import unittest
from pathlib import Path

import _paths
ROOT = _paths.APP
spec = importlib.util.spec_from_file_location("atlas_coding_swarm_worker", ROOT / "agents" / "atlas_coding_swarm_worker.py")
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)

class WorkerValidationTests(unittest.TestCase):
    def test_rejects_missing_request(self):
        with self.assertRaises(ValueError): worker.execute({"payload": {}})
    def test_rejects_unsupported_test_profile(self):
        with self.assertRaises(ValueError): worker.execute({"payload": {"request": "make thing", "test_profile": "powershell"}})
    def test_rejects_invalid_repair_count(self):
        with self.assertRaises(ValueError): worker.execute({"payload": {"request": "make thing", "max_repairs": 99}})

if __name__ == "__main__": unittest.main()
