"""Safe, feature-complete Markdown rendering for Nova desktop chat."""
from __future__ import annotations

import re

import bleach
import markdown

_RTL_TEXT = re.compile(r"[\\u0590-\\u08FF\\uFB1D-\\uFDFF\\uFE70-\\uFEFF]")

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
    """Render sanitized Markdown HTML with a direction-aware root for Qt.

    Qt's rich-text document does not infer paragraph direction reliably from
    Arabic/Persian glyphs. Marking the whole rendered message as RTL (or LTR)
    lets Qt's bidi engine lay out paragraphs, lists, tables and mixed-script
    text consistently without changing the Markdown content itself.
    """
    source = str(source or "")
    parser = markdown.Markdown(extensions=_EXTENSIONS, output_format="html5")
    rendered = parser.convert(source)
    sanitized = bleach.clean(
        rendered, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRIBUTES,
        protocols={"http", "https", "mailto"}, strip=True,
    )

    is_rtl = bool(_RTL_TEXT.search(source))
    direction = "rtl" if is_rtl else "ltr"
    alignment = "right" if is_rtl else "left"
    return (
        f'<div dir="{direction}" align="{alignment}">'
        f"{sanitized}"
        "</div>"
    )
