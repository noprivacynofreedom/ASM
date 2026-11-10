import os
import importlib
import pathlib
import sys
import tempfile
import unittest
ROOT = pathlib.Path(__file__).resolve().parents[1] / 'src-tauri' / 'resources' / 'atlas'  # shipped backend
COMMANDER = ROOT / 'src' / 'mcp_commander.py'
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
# Other unit tests stubbed this module; explicitly load the real MCP host here.
sys.modules.pop('mcp_monitor', None)
MCPMonitor = importlib.import_module('mcp_monitor').MCPMonitor

class RealMCPStdioTests(unittest.TestCase):
    def test_initialize_discover_call_and_independent_verification(self):
        with tempfile.TemporaryDirectory() as folder:
            sample = pathlib.Path(folder) / 'proof.txt'
            sample.write_text('atlas mcp smoke test', encoding='utf-8')
            # The monitor uses inherited environment; scope is set for this process only.
            old = os.environ.get('ATLAS_WORKSPACE')
            os.environ['ATLAS_WORKSPACE'] = folder
            monitor = MCPMonitor([{'name':'commander-test','command':[sys.executable,'-u',str(COMMANDER)],'cwd':str(ROOT)}])
            try:
                status = monitor.check_all()
                self.assertEqual(status['online'], 1)
                names = {x['name'] for x in status['servers'][0]['tools']}
                self.assertIn('list_workspace_files', names)
                self.assertIn('verify_workspace_file', names)
                listing = monitor.call_tool('commander-test','list_workspace_files',{'path':'.'})
                self.assertEqual(listing['status'], 'EXECUTED_UNVERIFIED')
                self.assertIn('proof.txt', str(listing['result']))
                verified = monitor.call_tool('commander-test','verify_workspace_file',{'path':'proof.txt'})
                self.assertEqual(verified['status'], 'VERIFIED')
                self.assertTrue(verified['result']['structuredContent']['verified'])
            finally:
                monitor.stop_all()
                if old is None: os.environ.pop('ATLAS_WORKSPACE', None)
                else: os.environ['ATLAS_WORKSPACE'] = old

if __name__ == '__main__': unittest.main()
