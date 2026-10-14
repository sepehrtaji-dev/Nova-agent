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
        self.assertIn("\nTitle: Example Article", result)
        self.assertNotIn("\\nTitle: Example Article", result)
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

    def test_whitespace_query_variants_never_reach_the_network(self):
        """Regression: a whitespace-only dict query was treated as valid.

        _parse_input returned the raw value for dict input, so "   " passed the
        emptiness check and real HTTP requests were made for a blank search.
        """
        for payload in (
            {"query": "   "},
            {"query": "\t\n "},
            {"search": "  "},
            {"q": ""},
            {"query": None},
            {},
            "   ",
            '{"query": "   "}',
        ):
            with patch("urllib.request.urlopen") as urlopen:
                result = self.tool.run(payload)
            self.assertIn("query is empty", result.lower(), repr(payload))
            urlopen.assert_not_called()

    def test_query_alternate_keys_are_accepted_and_stripped(self):
        for key in ("query", "search", "q", "text"):
            self.assertEqual(
                self.tool._parse_input({key: "  nova agent  "}),
                "nova agent",
                key,
            )
        self.assertEqual(
            self.tool._parse_input('{"query": "  spaced  "}'), "spaced"
        )

    @patch("urllib.request.urlopen")
    def test_reports_provider_failure_instead_of_fabricating_results(self, urlopen):
        urlopen.side_effect = OSError("network unavailable")

        result = self.tool.run({"query": "current events"})

        self.assertIn("no usable results", result.lower())
        self.assertIn("network unavailable", result.lower())
        self.assertNotIn("Title:", result)


class WebFetchUrlValidationTests(unittest.TestCase):
    """Scheme validation must raise ValueError, which is what callers catch."""

    def setUp(self):
        self.tool = WebSearchTool()

    def test_non_http_schemes_raise_value_error(self):
        """Regression: a bad scheme raised TypeError, escaping fetch()'s handler.

        Callers catch ValueError around URL validation, so a TypeError escaped
        and crashed instead of producing a clean error string.
        """
        for url in (
            "file:///etc/passwd",
            "ftp://example.com/x",
            "javascript:alert(1)",
            "data:text/html,<b>x</b>",
            "gopher://example.com",
        ):
            with self.assertRaises(ValueError, msg=url):
                self.tool._validate_public_url(url)

    def test_fetch_returns_error_string_for_bad_scheme(self):
        result = self.tool.fetch({"url": "file:///etc/passwd"})
        self.assertTrue(result.startswith("WEB_FETCH_ERROR:"), result)


class WebTextSanitizerTests(unittest.TestCase):
    def setUp(self):
        self.tool = WebSearchTool()

    def test_international_text_is_preserved(self):
        for value in ("使用手册", "مرحبا بالعالم", "سلام دنیا", "Café résumé"):
            self.assertEqual(self.tool._clean_text(value, 300), value)

    def test_control_and_bidi_characters_are_stripped(self):
        self.assertNotIn("\x00", self.tool._clean_text("a\x00b", 300))
        self.assertNotIn("\x07", self.tool._clean_text("a\x07b", 300))
        self.assertNotIn("\x1b", self.tool._clean_text("a\x1b[31m", 300))
        # A right-to-left override can visually reorder displayed text.
        self.assertEqual(self.tool._clean_text("evil\u202etxt", 300), "eviltxt")

    def test_entities_and_whitespace_are_normalized(self):
        self.assertEqual(self.tool._clean_text("Tom &amp; Jerry", 300), "Tom & Jerry")
        self.assertEqual(self.tool._clean_text("  a   b  ", 300), "a b")
        self.assertEqual(len(self.tool._clean_text("x" * 500, 300)), 300)


class WebResultRelevanceTests(unittest.TestCase):
    """A provider answering 200 with unrelated results must not be trusted."""

    def setUp(self):
        self.tool = WebSearchTool()

    def test_off_topic_results_score_zero(self):
        cleaned = [
            ("my.gov.ir https://my.gov.ir", "https://my.gov.ir", "login portal"),
            ("iran.gov.ir", "https://iran.gov.ir/fa", "national services"),
        ]
        self.assertEqual(WebSearchTool._relevance(cleaned, "best minecraft shaders 2026"), 0.0)

    def test_on_topic_results_score_positive(self):
        cleaned = [
            ("10+ Best Minecraft Shaders 2026", "https://x.com/a",
             "explore realistic shader packs"),
        ]
        self.assertGreater(WebSearchTool._relevance(cleaned, "best minecraft shaders 2026"), 0.0)

    def test_short_query_terms_do_not_filter(self):
        self.assertEqual(WebSearchTool._relevance([("a", "b", "c")], "a b"), 1.0)

    @patch("urllib.request.urlopen")
    def test_unrelated_provider_response_is_rejected(self, urlopen):
        """End-to-end: an off-topic SERP must produce an error, not fake results."""
        urlopen.return_value = FakeResponse("""
            <html><body>
              <div class="result results_links">
                <div class="result__body">
                  <h2><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fmy.gov.ir%2F">
                    my.gov.ir https://my.gov.ir
                  </a></h2>
                  <div class="result__snippet">National government services portal.</div>
                </div>
              </div>
            </body></html>
        """)
        result = self.tool.run({"query": "best minecraft shaders 2026"})
        self.assertIn("no usable results", result.lower())
        self.assertNotIn("my.gov.ir", result)

    @patch("urllib.request.urlopen")
    def test_protocol_relative_duckduckgo_links_are_unwrapped(self, urlopen):
        """Regression: DDG returns '//duckduckgo.com/l/?uddg=...' links.

        urlsplit gives those no hostname, so the uddg unwrap was skipped and the
        scheme check then discarded every real hit, losing all results.
        """
        urlopen.return_value = FakeResponse("""
            <html><body>
              <div class="result results_links">
                <div class="result__body">
                  <h2><a class="result__a"
                     href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fmusthavemods.com%2Fbest-minecraft-shaders-2026%2F">
                    Best Minecraft Shaders 2026
                  </a></h2>
                  <div class="result__snippet">Explore realistic minecraft shader packs.</div>
                </div>
              </div>
            </body></html>
        """)
        result = self.tool.run({"query": "best minecraft shaders 2026"})
        self.assertIn("https://musthavemods.com/best-minecraft-shaders-2026/", result)
        self.assertNotIn("duckduckgo.com", result)


if __name__ == "__main__":
    unittest.main()
