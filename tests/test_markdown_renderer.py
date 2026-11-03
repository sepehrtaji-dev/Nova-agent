import unittest
from ui.markdown_renderer import render_markdown


class MarkdownRendererTests(unittest.TestCase):
    def test_gfm_style_table_renders_as_html_table(self):
        rendered = render_markdown(
            "| Model | Parameters | Status |\n"
            "|:------|-----------:|:------:|\n"
            "| Nova | 31B | **Ready** |\n"
        )
        self.assertIn("<table>", rendered)
        self.assertIn("<th", rendered)
        self.assertIn("<td", rendered)
        self.assertIn("<strong>Ready</strong>", rendered)
        self.assertNotIn("| Model |", rendered)

    def test_nested_lists_and_blockquotes(self):
        rendered = render_markdown(
            "> Summary\n\n- first\n  - nested\n\n1. second\n"
        )
        self.assertIn("<blockquote>", rendered)
        self.assertIn("<ul>", rendered)
        self.assertIn("<ol>", rendered)
        self.assertIn("nested", rendered)

    def test_fenced_code_and_inline_code(self):
        rendered = render_markdown("Run `python app.py`:\n\n    print(1)\n")
        self.assertIn("<code>python app.py</code>", rendered)
        self.assertIn("<pre>", rendered)
        self.assertIn("print(1)", rendered)

    def test_links_emphasis_and_strikethrough(self):
        rendered = render_markdown(
            "**bold**, *italic*, ~~removed~~ and [Nova](https://example.com)"
        )
        self.assertIn("<strong>bold</strong>", rendered)
        self.assertIn("<em>italic</em>", rendered)
        self.assertIn("<del>removed</del>", rendered)
        self.assertIn('href="https://example.com"', rendered)

    def test_script_html_is_removed(self):
        rendered = render_markdown('<img src="x" onerror="alert(1)">')
        self.assertNotIn("<script", rendered)
        self.assertNotIn("onerror", rendered)


if __name__ == "__main__":
    unittest.main()
