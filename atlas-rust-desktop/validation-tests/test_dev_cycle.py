import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
import dev_cycle

class DevCycleTests(unittest.TestCase):
    def test_fixed_command_runner_reports_success(self):
        result = dev_cycle._run_step('python smoke test', [dev_cycle.sys.executable, '-c', 'print("atlas-ok")'])
        self.assertEqual(result['status'], 'passed')
        self.assertIn('atlas-ok', result['stdout'])

    def test_fixed_command_runner_reports_failure(self):
        result = dev_cycle._run_step('expected failure', [dev_cycle.sys.executable, '-c', 'raise SystemExit(7)'])
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['returncode'], 7)

    def test_feedback_requires_cycle_id(self):
        result = dev_cycle.submit_feedback({})
        self.assertFalse(result['ok'])

    def test_agent_context_empty_without_feedback(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(dev_cycle, 'STATE_FILE', Path(folder) / 'cycles.json'):
                self.assertEqual(dev_cycle.get_agent_context(), '')

if __name__ == '__main__':
    unittest.main()
