import unittest
from unittest.mock import patch

from tools.web import WebSearchTool


class FakeResponse:
    def __init__(self, body, status=200):
        self._body = body.encode("utf-8")
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size=-1):
        return self._body[:size]


class WebSearchTests(unittest.TestCase):
    def setUp(self):
        self.tool = WebSearchTool()

    @patch("urllib.request.urlopen")
    def test_parses_realistic_duckduckgo_result_markup(self, urlopen):
        urlopen.return_value = FakeResponse("""
            <html><body>
              <div class="result results_links results_links_deep">
                <div class="result__body">
                  <h2><a class="result__a" href="https://example.org/article">
                    Example Article
                  </a></h2>
                  <div class="result__snippet">A useful search result snippet.</div>
                </div>
              </div>
            </body></html>
        """)

        result = self.tool.run({"query": "example article"})

        self.assertIn("Title: Example Article", result)
        self.assertIn("URL: https://example.org/article", result)
        self.assertIn("Snippet: A useful search result snippet.", result)
        self.assertIn("\\nTitle: Example Article", result)
        self.assertNotIn("\\\\nTitle: Example Article", result)
        self.assertEqual(urlopen.call_count, 1)

    @patch("urllib.request.urlopen")
    def test_falls_back_to_second_provider_when_first_has_no_results(self, urlopen):
        urlopen.side_effect = [
            FakeResponse("<html><body>no results markup</body></html>"),
            FakeResponse("""
                <ol>
                  <li class="b_algo">
                    <h2><a href="https://example.net/docs">Example Docs</a></h2>
                    <div class="b_caption"><p>Documentation result.</p></div>
                  </li>
                </ol>
            """),
        ]

        result = self.tool.run({"query": "example docs"})

        self.assertIn("Title: Example Docs", result)
        self.assertIn("URL: https://example.net/docs", result)
        self.assertIn("Snippet: Documentation result.", result)
        self.assertEqual(urlopen.call_count, 2)

    def test_rejects_empty_query_without_network_request(self):
        with patch("urllib.request.urlopen") as urlopen:
            result = self.tool.run({"query": "   "})

        self.assertIn("query is empty", result.lower())
        urlopen.assert_not_called()

    @patch("urllib.request.urlopen")
    def test_reports_provider_failure_instead_of_fabricating_results(self, urlopen):
        urlopen.side_effect = OSError("network unavailable")

        result = self.tool.run({"query": "current events"})

        self.assertIn("no usable results", result.lower())
        self.assertIn("network unavailable", result.lower())
        self.assertNotIn("Title:", result)


if __name__ == "__main__":
    unittest.main()
