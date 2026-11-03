"""Safe, feature-complete Markdown rendering for Nova desktop chat."""
from __future__ import annotations

import bleach
import markdown

_ALLOWED_TAGS = set(bleach.sanitizer.ALLOWED_TAGS) | {
    "p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6",
    "blockquote", "pre", "code", "span", "div",
    "ul", "ol", "li", "dl", "dt", "dd",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td",
    "del", "ins", "sup", "sub", "img", "input",
}
_ALLOWED_ATTRIBUTES = {
    "a": ["href", "title"],
    "img": ["src", "alt", "title", "width", "height"],
    "code": ["class"], "pre": ["class"],
    "th": ["align"], "td": ["align"], "ol": ["start"],
    "input": ["type", "checked", "disabled"],
}
_EXTENSIONS = ["extra", "sane_lists", "nl2br", "pymdownx.tilde"]

def render_markdown(source: str) -> str:
    """Render Markdown to sanitized HTML suitable for QTextBrowser."""
    parser = markdown.Markdown(extensions=_EXTENSIONS, output_format="html5")
    rendered = parser.convert(str(source or ""))
    return bleach.clean(
        rendered, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRIBUTES,
        protocols={"http", "https", "mailto"}, strip=True,
    )
