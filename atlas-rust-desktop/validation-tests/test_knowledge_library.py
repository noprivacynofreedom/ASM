import json
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

# Keep this module independently testable without starting real MCP subprocesses.
sys.modules.setdefault('docsearch', types.SimpleNamespace(search=lambda *_: [], prompt_block=lambda *_: ''))
class _MCPStub:
    def __init__(self, *_): pass
    def stop_all(self): pass
    def status(self): return {'configured': 0, 'online': 0, 'servers': []}
    def check_all(self): return self.status()
    def call_tool(self, *_args, **_kwargs): return {'status': 'FAILED', 'verification': 'failed'}
sys.modules.setdefault('mcp_monitor', types.SimpleNamespace(MCPMonitor=_MCPStub))

import server

class _FakeResponse:
    status = 200
    def read(self):
        return json.dumps({'choices': [{'message': {'content': '# Study capsule\n\nGrounded notes.'}}]}).encode()

class _FakeConnection:
    last_request = None
    def __init__(self, *_args, **_kwargs): pass
    def request(self, method, path, body=None, headers=None):
        self.__class__.last_request = json.loads(body.decode())
    def getresponse(self): return _FakeResponse()
    def close(self): pass

class KnowledgeLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_dir, self.old_index = server.LIBRARY_DIR, server.LIBRARY_INDEX
        server.LIBRARY_DIR = self.tmp.name
        server.LIBRARY_INDEX = os.path.join(self.tmp.name, 'index.json')

    def tearDown(self):
        server.LIBRARY_DIR, server.LIBRARY_INDEX = self.old_dir, self.old_index
        self.tmp.cleanup()

    def test_source_index_round_trip(self):
        source_id = 'a' * 20
        os.makedirs(server.LIBRARY_DIR, exist_ok=True)
        with open(server._library_item_path(source_id), 'w', encoding='utf-8') as f: f.write('# Atlas notes')
        server._save_library_index({'items': [{'id': source_id, 'name': 'notes.md'}], 'distillations': []})
        self.assertEqual(server._library_index()['items'][0]['name'], 'notes.md')

    def test_distillation_calls_selected_local_model_and_persists_capsule(self):
        source_id = 'b' * 20
        os.makedirs(server.LIBRARY_DIR, exist_ok=True)
        with open(server._library_item_path(source_id), 'w', encoding='utf-8') as f:
            f.write('# Networking\nDHCP assigns IP configuration to clients.')
        server._save_library_index({'items': [{'id': source_id, 'name': 'networking.md'}], 'distillations': []})
        with patch.object(server.http.client, 'HTTPConnection', _FakeConnection):
            result = server._library_distill({'ids': [source_id], 'model': 'mentor-dense'})
        self.assertTrue(result['ok'])
        self.assertEqual(_FakeConnection.last_request['model'], 'mentor-dense')
        self.assertIn('networking.md', _FakeConnection.last_request['messages'][1]['content'])
        saved = server._library_index()['distillations'][0]
        self.assertEqual(saved['source_ids'], [source_id])
        self.assertIn('Grounded notes', saved['content'])

    def test_distillation_processes_sources_beyond_old_120k_limit(self):
        source_id = 'd' * 20
        os.makedirs(server.LIBRARY_DIR, exist_ok=True)
        long_text = ('A sufficiently detailed source statement about Atlas knowledge retrieval.\n' * 2600)
        with open(server._library_item_path(source_id), 'w', encoding='utf-8') as f: f.write(long_text)
        server._save_library_index({'items': [{'id': source_id, 'name': 'large-notes.md'}], 'distillations': []})
        with patch.object(server.http.client, 'HTTPConnection', _FakeConnection):
            result = server._library_distill({'ids': [source_id], 'model': 'mentor-dense'})
        self.assertTrue(result['ok'])
        self.assertGreater(result['stats']['input_bytes'], 120000)
        self.assertGreater(result['stats']['chunks_processed'], 1)

    def test_student_pack_contains_knowledge_graph_and_training_jsonl(self):
        import zipfile, io
        record = {'id':'e'*20,'title':'Networking capsule','model':'mentor-dense','teacher_model':'mentor-dense',
                  'source_ids':['a'*20],'source_names':['networking.md'],'created_at':1,'content':'# DHCP',
                  'concepts':[{'name':'DHCP','type':'protocol'}],
                  'relationships':[{'from':'DHCP','to':'IP lease','relation':'assigns'}],
                  'training_examples':[{'question':'What does DHCP assign?','answer':'IP configuration.','source_ids':['a'*20]}]}
        server._save_library_index({'items':[],'distillations':[record]})
        data, filename = server._library_student_pack(record['id'])
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertIn('knowledge.md', archive.namelist())
            self.assertIn('graph.json', archive.namelist())
            training=archive.read('training.jsonl').decode()
            self.assertIn('What does DHCP assign?', training)
            self.assertIn('Networking capsule', archive.read('manifest.json').decode())

    def test_rejects_unknown_source_ids(self):
        server._save_library_index({'items': [], 'distillations': []})
        with self.assertRaises(ValueError): server._library_distill({'ids': ['c' * 20]})

if __name__ == '__main__': unittest.main()
