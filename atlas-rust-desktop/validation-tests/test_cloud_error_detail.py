"""A cloud HTTP error must state the provider's reason (refusal, quota, bad request), not just a code."""
import io
import sys
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src-tauri" / "resources" / "atlas"))
import cloud_llm  # noqa: E402


def http_error(code, body):
    return urllib.error.HTTPError("http://x", code, "err", {}, io.BytesIO(body.encode()))


class CloudErrorDetail(unittest.TestCase):
    def test_detail_pulls_the_provider_message(self):
        d = cloud_llm._http_detail(http_error(402, '{"error":{"message":"You exceeded your current quota.","status":"RESOURCE_EXHAUSTED"}}'))
        self.assertIn("You exceeded your current quota.", d)

    def test_detail_handles_plain_text_and_empty(self):
        self.assertIn("Service Unavailable", cloud_llm._http_detail(http_error(503, "Service Unavailable")))
        self.assertEqual(cloud_llm._http_detail(http_error(500, "")), "")

    def test_detail_handles_string_error_and_nested(self):
        self.assertIn("model is overloaded", cloud_llm._http_detail(http_error(429, '{"error":"model is overloaded"}')))

    def test_post_raises_cloud_error_with_reason(self):
        orig = cloud_llm._opener

        class FakeOpener:
            def open(self, *a, **k):
                raise http_error(403, '{"error":{"message":"Safety: the request was blocked."}}')
        cloud_llm._opener = lambda: FakeOpener()
        try:
            with self.assertRaises(cloud_llm.CloudError) as cm:
                cloud_llm._post("http://x", {}, {}, 5)
            msg = str(cm.exception)
            self.assertIn("HTTP 403", msg)
            self.assertIn("Safety: the request was blocked.", msg)
            self.assertEqual(cm.exception.code, 403)
        finally:
            cloud_llm._opener = orig


if __name__ == "__main__":
    unittest.main()
