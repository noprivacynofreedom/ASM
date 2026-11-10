import unittest
import sys
import types
import knowledge_engine

class KnowledgeEngineTests(unittest.TestCase):
    def test_chunking_covers_long_input_with_overlap(self):
        text=('alpha beta gamma delta. ' * 1200)
        parts=knowledge_engine.chunks(text,size=1000,overlap=100)
        self.assertGreater(len(parts),2)
        self.assertIn('gamma', ' '.join(parts))
        self.assertGreaterEqual(sum(len(x) for x in parts),len(text)*0.8)

    def test_lexical_retrieval_returns_relevant_source(self):
        records=[
            {'id':'a','kind':'source','title':'networking.md','text':'DHCP assigns IP addresses to clients using leases.'},
            {'id':'b','kind':'source','title':'cooking.md','text':'A sourdough starter uses flour and water.'}
        ]
        result=knowledge_engine.search(records,'DHCP IP address lease', '127.0.0.1',8080,'',5)
        self.assertTrue(result)
        self.assertEqual(result[0]['title'],'networking.md')

    def test_fastembed_backend_adapter_and_vector_ranking(self):
        class FakeEmbedding:
            def __init__(self, model_name): self.model_name=model_name
            def embed(self, texts):
                for text in texts:
                    words=set(knowledge_engine._tokens(text))
                    yield [1.0 if 'dhcp' in words else 0.0, 1.0 if 'sourdough' in words else 0.0]
        sys.modules['fastembed']=types.SimpleNamespace(TextEmbedding=FakeEmbedding)
        knowledge_engine._FASTEMBED_CACHE.pop('test-local-model',None)
        records=[{'id':'a','kind':'source','title':'networking','text':'DHCP leases'},{'id':'b','kind':'source','title':'bread','text':'sourdough starter'}]
        vectors=knowledge_engine.embed([x['text'] for x in records],'127.0.0.1',8080,'fastembed:test-local-model')
        for record,vector in zip(records,vectors): record['vector']=vector
        hits=knowledge_engine.search(records,'DHCP configuration','127.0.0.1',8080,'fastembed:test-local-model',2)
        self.assertEqual(hits[0]['title'],'networking')

    def test_graph_preserves_source_relationships(self):
        graph=knowledge_engine.graph_from_capsules([{'source_ids':['abc'],'concepts':[{'name':'DHCP'}], 'relationships':[{'from':'DHCP','to':'IP lease','relation':'assigns'}]}])
        self.assertEqual(len(graph['nodes']),2)
        self.assertEqual(graph['edges'][0]['relation'],'assigns')
        self.assertIn('abc',graph['nodes'][0]['sources'])

if __name__=='__main__': unittest.main()
