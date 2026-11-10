import base64
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

import _paths
ROOT = _paths.APP
_TMP = tempfile.TemporaryDirectory(prefix='atlas-evidence-tests-')
os.environ['ATLAS_OBSERVABILITY_DB'] = str(Path(_TMP.name) / 'ops.sqlite3')
spec = importlib.util.spec_from_file_location('atlas_observability_under_test', ROOT / 'atlas_observability.py')
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)


class TaskEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.agent = ops.register({'name': 'evidence-test'})
        self.agent_id, self.token = self.agent['agent_id'], self.agent['token']
        self.task = ops.submit_task({'type': 'programming', 'trace_id': 'trace-evidence-001', 'payload': {'project_name': 'demo', 'files': {'a.txt': 'hello'}}})

    def test_events_and_frames_are_correlated(self):
        self.assertTrue(ops.ingest_event(self.agent_id, self.token, {
            'task_id': self.task['task_id'], 'trace_id': self.task['trace_id'],
            'kind': 'worker.stage', 'message': 'writing files', 'details': {'stage': 'write'}
        }))
        png = b'\x89PNG\r\n\x1a\n' + b'valid-test-payload'
        frame_id = ops.ingest_frame(self.agent_id, self.token, {
            'task_id': self.task['task_id'], 'trace_id': self.task['trace_id'],
            'mime': 'image/png', 'data': base64.b64encode(png).decode(), 'caption': 'milestone'
        })
        bundle = ops.task_evidence(self.task['task_id'])
        self.assertEqual(bundle['task']['task_id'], self.task['task_id'])
        self.assertEqual(bundle['trace_id'], self.task['trace_id'])
        self.assertTrue(any(e['kind'] == 'worker.stage' for e in bundle['events']))
        self.assertTrue(any(f['frame_id'] == frame_id for f in bundle['frames']))
        self.assertEqual(bundle['evidence_status'], 'unverified')
        self.assertNotIn('data', bundle['frames'][0])

    def test_missing_task_returns_none(self):
        self.assertIsNone(ops.task_evidence('tsk_missing'))

    def test_frame_rejects_mismatched_signature(self):
        with self.assertRaises(ValueError):
            ops.ingest_frame(self.agent_id, self.token, {
                'task_id': self.task['task_id'], 'mime': 'image/png',
                'data': base64.b64encode(b'not-an-image').decode()
            })

    def test_old_frames_schema_migrates(self):
        with ops._db() as conn:
            cols = {r['name'] for r in conn.execute('PRAGMA table_info(frames)')}
        self.assertIn('task_id', cols)
        self.assertIn('trace_id', cols)


if __name__ == '__main__':
    unittest.main(verbosity=2)
