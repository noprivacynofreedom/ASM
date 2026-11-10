import _paths  # noqa: F401
import ast
import pathlib
import unittest


class MCPServerAuditWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = _paths.APP / "server.py"
        cls.tree = ast.parse(source.read_text(encoding="utf-8"))

    def test_chat_and_manual_routes_use_same_canonical_recorder(self):
        calls = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "_MCP_AUDIT_RECORDER":
                    if node.func.attr == "record":
                        calls.append(node)
        self.assertEqual(len(calls), 3)
        # One call is the chat callback; two are manual success and exception paths.

    def test_recorder_is_bound_to_existing_bounded_audit_deque_and_ops_sink(self):
        source = _paths.APP / "server.py"
        text = source.read_text(encoding="utf-8")
        self.assertIn("_MCP_AUDIT = deque(maxlen=200)", text)
        self.assertIn(
            "MCPAuditRecorder(_MCP_AUDIT, _MCP_AUDIT_LOCK, OPS.record_local_event)",
            text,
        )


if __name__ == "__main__":
    unittest.main()
