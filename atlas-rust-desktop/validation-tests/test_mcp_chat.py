import unittest
from unittest.mock import patch
import mcp_chat

class FakeMonitor:
    def status(self):
        return {"servers":[{"name":"safe-files","state":"online","process_running":True,
            "tools":[{"name":"list_files","description":"List files","inputSchema":{"type":"object","properties":{}}}]}]}
    def call_tool(self, server, tool, args, timeout=30):
        return {"server":server,"tool":tool,"status":"EXECUTED_UNVERIFIED","verification":"not_performed",
                "result":{"content":[{"type":"text","text":"file-a.py"}]}}

class MCPChatTests(unittest.TestCase):
    @patch('mcp_chat._post_completion')
    def test_tool_call_is_executed_then_returned_to_model(self, post):
        post.side_effect = [
            {"id":"1","model":"test","choices":[{"message":{"role":"assistant","content":None,
                "tool_calls":[{"id":"call-1","type":"function","function":{"name":"safe-files__list_files","arguments":"{}"}}]},"finish_reason":"tool_calls"}]},
            {"id":"2","model":"test","choices":[{"message":{"role":"assistant","content":"I found file-a.py."},"finish_reason":"stop"}]}
        ]
        events=[]
        result, audit=mcp_chat.run_tool_loop({"messages":[{"role":"user","content":"List files"}],"stream":True},
            FakeMonitor(),events.append,'127.0.0.1',8080)
        self.assertEqual(result['choices'][0]['message']['content'],'I found file-a.py.')
        self.assertEqual(len(audit),1)
        self.assertEqual(audit[0]['status'],'EXECUTED_UNVERIFIED')
        sent=post.call_args_list[1].args[2]['messages']
        self.assertEqual(sent[-1]['role'],'tool')
        self.assertIn('file-a.py',sent[-1]['content'])

    def test_sse_encoder_returns_done_marker(self):
        response={"id":"x","model":"test","choices":[{"message":{"content":"hello"},"finish_reason":"stop"}]}
        stream=mcp_chat.as_sse(response)
        self.assertIn('"content": "hello"',stream)
        self.assertTrue(stream.endswith('data: [DONE]\n\n'))

if __name__=='__main__': unittest.main()
