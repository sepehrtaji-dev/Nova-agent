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

    def test_compact_english_table_after_heading_without_blank_lines(self):
        rendered = render_markdown(
            "## Comparison\n"
            "| Feature | Nova | Cloud |\n"
            "|:---|:---:|---:|\n"
            "| Markdown | Yes | Yes |\n"
            "Next paragraph."
        )
        self.assertIn("<h2>Comparison</h2>", rendered)
        self.assertIn("<table>", rendered)
        self.assertIn("<td>Markdown</td>", rendered)
        self.assertIn("Next paragraph.", rendered)
        self.assertNotIn("| Feature |", rendered)

    def test_compact_persian_table_after_heading_without_blank_lines(self):
        rendered = render_markdown(
            "## خلاصه تفاوت‌ها\n"
            "| ویژگی | نوا | چت‌جی‌پی‌تی |\n"
            "|:---|:---:|---:|\n"
            "| پشتیبانی فارسی | بله | بله |\n"
            "پایان جدول."
        )
        self.assertIn('<div dir="rtl" align="right">', rendered)
        self.assertIn("<table>", rendered)
        self.assertIn("<td>ویژگی</td>", rendered)
        self.assertIn("<td>پشتیبانی فارسی</td>", rendered)
        self.assertIn("پایان جدول.", rendered)
        self.assertNotIn("| ویژگی |", rendered)

    def test_table_pipes_inside_fenced_code_are_not_rewritten(self):
        rendered = render_markdown(
            "~~~text\n| A | B |\n|---|---|\n~~~\n"
        )
        self.assertNotIn("<table>", rendered)
        self.assertIn("| A | B |", rendered)

    def test_nested_lists_and_blockquotes(self):
        rendered = render_markdown(
            "> Summary\n\n- first\n  - nested\n\n1. second\n"
        )
        self.assertIn("<blockquote>", rendered)
        self.assertIn("<ul>", rendered)
        self.assertIn("<ol>", rendered)
        self.assertIn("nested", rendered)

    def test_fenced_code_and_inline_code(self):
        tick = chr(96)
        rendered = render_markdown("Run " + tick + "python app.py" + tick + ":\n\n    print(1)\n")
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

    def test_persian_markdown_uses_rtl_layout(self):
        rendered = render_markdown(
            "# راهنمای نوا\n\n"
            "این یک متن **فارسی** با عبارت Nova و عدد 31B است.\n\n"
            "- مورد اول\n- مورد دوم"
        )
        self.assertIn('<div dir="rtl" align="right">', rendered)
        self.assertIn("<h1>راهنمای نوا</h1>", rendered)
        self.assertIn("<strong>فارسی</strong>", rendered)
        self.assertIn("Nova", rendered)
        self.assertIn("<ul>", rendered)

    def test_english_markdown_keeps_ltr_layout(self):
        rendered = render_markdown("# Nova\n\nEnglish response")
        self.assertIn('<div dir="ltr" align="left">', rendered)

    def test_script_html_is_removed(self):
        rendered = render_markdown('<img src="x" onerror="alert(1)">')
        self.assertNotIn("<script", rendered)
        self.assertNotIn("onerror", rendered)


if __name__ == "__main__":
    unittest.main()
