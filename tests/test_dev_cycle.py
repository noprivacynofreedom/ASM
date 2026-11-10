"""Regression tests for the Atlas Development Cycle runner."""
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import _paths  # noqa: F401  (shipped code first on sys.path)
import dev_cycle


class DevelopmentCycleTests(unittest.TestCase):
    def test_python_discovery_runs_unittest_discovery_not_script_smoke_file(self):
        old_current = dev_cycle._CURRENT
        # _execute only runs the test stage when ROOT has a tests folder, and it
        # saves history under STATE_DIR: use a throwaway folder for both.
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp:
            root = Path(temp)
            (root / "tests").mkdir()
            (root / "tests" / "test_sample.py").write_text("pass\n", encoding="utf-8")
            state_dir = root / ".atlas"
            with patch.object(dev_cycle, "ROOT", root), \
                    patch.object(dev_cycle, "STATE_DIR", state_dir), \
                    patch.object(dev_cycle, "STATE_FILE", state_dir / "dev_cycles.json"), \
                    patch.object(dev_cycle, "_run_step", return_value={"name": "step", "status": "passed"}) as run:
                # The production command is asserted directly so future edits cannot
                # silently regress to a discovery path that reports zero tests.
                dev_cycle._execute("test-cycle")
        dev_cycle._CURRENT = old_current
        calls = [call.args for call in run.call_args_list]
        test_call = next(args for args in calls if args[0] == "Python automated tests")
        self.assertEqual(test_call[1][1:4], ["-m", "unittest", "discover"])
        self.assertIn("-s", test_call[1])
        self.assertIn("tests", test_call[1])

    def test_step_command_is_run_without_shell(self):
        with patch.object(dev_cycle.subprocess, "run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "ok"
            run.return_value.stderr = ""
            result = dev_cycle._run_step("safe test", ["python", "-V"])
        self.assertEqual(result["status"], "passed")
        self.assertIs(run.call_args.kwargs["shell"], False)

    def test_live_status_exposes_completed_and_current_steps(self):
        old_current = dev_cycle._CURRENT
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp:
            root = Path(temp)
            (root / "tests").mkdir()
            (root / "tests" / "test_sample.py").write_text("pass\n", encoding="utf-8")
            state_dir = root / ".atlas"
            with patch.object(dev_cycle, "ROOT", root), \
                    patch.object(dev_cycle, "STATE_DIR", state_dir), \
                    patch.object(dev_cycle, "STATE_FILE", state_dir / "dev_cycles.json"):
                dev_cycle._CURRENT = {
                    "id": "live-cycle", "status": "running", "started_at": 0,
                    "steps": [], "current_step": None,
                }

                def inspect_progress(name, args, timeout=180):
                    status = dev_cycle.get_status()["cycle"]
                    self.assertEqual(status["current_step"], name)
                    self.assertEqual(len(status["steps"]), 0 if name == "Python automated tests" else 1)
                    return {"name": name, "status": "passed", "returncode": 0,
                            "stdout": "", "stderr": "", "duration_seconds": 0}

                with patch.object(dev_cycle, "_run_step", side_effect=inspect_progress):
                    cycle = dev_cycle._execute("live-cycle")

                self.assertEqual(cycle["status"], "passed")
                self.assertEqual([s["status"] for s in cycle["steps"]], ["passed", "passed"])
        dev_cycle._CURRENT = old_current


if __name__ == "__main__":
    unittest.main()
