import unittest

from agent.verifier import Verifier
from tools.web import WebSearchTool


class WebFetchSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tool = WebSearchTool()

    def test_rejects_non_http_scheme(self):
        with self.assertRaises(ValueError):
            self.tool._validate_public_url("file:///etc/passwd")

    def test_rejects_loopback_ip(self):
        with self.assertRaises(ValueError):
            self.tool._validate_public_url("http://127.0.0.1/")

    def test_rejects_local_hostname(self):
        with self.assertRaises(ValueError):
            self.tool._validate_public_url("http://localhost/")

    def test_rejects_credentials_in_url(self):
        with self.assertRaises(ValueError):
            self.tool._validate_public_url("https://user:pass@example.com/")

    def test_rejects_nonstandard_port(self):
        with self.assertRaises(ValueError):
            self.tool._validate_public_url("https://example.com:444/")

    def test_fetch_returns_clear_error_for_local_url(self):
        result = self.tool.fetch({"url": "http://127.0.0.1/"})
        self.assertTrue(result.startswith("WEB_FETCH_ERROR:"))

    def test_verifier_rejects_empty_or_malformed_fetch_result(self):
        verifier = Verifier(tools=None)
        result = verifier.verify("web_fetch", {"url": "https://example.com"}, "WEB_FETCH_SUCCESS")
        self.assertEqual(result.status, "unverifiable")

    def test_verifier_confirms_structured_fetch_result(self):
        verifier = Verifier(tools=None)
        result = (
            "WEB_FETCH_SUCCESS\n"
            "URL: https://example.com/article\n"
            "Content-Type: text/html\n"
            "Characters: 12\n"
            "BEGIN_PAGE_TEXT\n"
            "Hello webpage\n"
            "END_PAGE_TEXT"
        )
        verification = verifier.verify("web_fetch", {"url": "https://example.com"}, result)
        self.assertTrue(verification.confirmed())

    def test_verifier_rejects_unsafe_fetch_url(self):
        verifier = Verifier(tools=None)
        result = (
            "WEB_FETCH_SUCCESS\n"
            "URL: javascript:alert(1)\n"
            "BEGIN_PAGE_TEXT\n"
            "Hello\n"
            "END_PAGE_TEXT"
        )
        verification = verifier.verify("web_fetch", {}, result)
        self.assertEqual(verification.status, "failed")


if __name__ == "__main__":
    unittest.main()
