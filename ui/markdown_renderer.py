"""Safe Markdown rendering for Nova desktop chat, including Persian RTL tables."""
from __future__ import annotations

import re

import bleach
import markdown

_RTL_TEXT = re.compile(r"[\u0590-\u08FF\uFB1D-\uFDFF\uFE70-\uFEFF]")
_TABLE_SEPARATOR_CELL = re.compile(r"^:?-{3,}:?$")


def _table_cells(line: str) -> list[str]:
    value = line.strip()
    if not value or "|" not in value:
        return []
    if value.startswith("|"):
        value = value[1:]
    if value.endswith("|") and not value.endswith(r"\|"):
        value = value[:-1]
    return [cell.strip() for cell in value.split("|")]


def _is_table_header(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    header = _table_cells(lines[index])
    separator = _table_cells(lines[index + 1])
    return (
        len(header) >= 2
        and len(header) == len(separator)
        and all(_TABLE_SEPARATOR_CELL.fullmatch(cell) for cell in separator)
    )


def _normalize_table_spacing(source: str) -> str:
    """Add block boundaries around compact tables without altering fenced code."""
    lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    output: list[str] = []
    in_fence = False
    fence_char = ""
    fence_size = 0
    index = 0

    while index < len(lines):
        line = lines[index]
        stripped = line.lstrip()
        marker_char = chr(96) if stripped.startswith(chr(96) * 3) else "~" if stripped.startswith("~~~") else ""
        if marker_char:
            marker_size = len(stripped) - len(stripped.lstrip(marker_char))
            if not in_fence:
                in_fence = True
                fence_char = marker_char
                fence_size = marker_size
            elif marker_char == fence_char and marker_size >= fence_size:
                in_fence = False
            output.append(line)
            index += 1
            continue

        if not in_fence and _is_table_header(lines, index):
            end = index + 2
            expected_cells = len(_table_cells(lines[index]))
            while end < len(lines):
                cells = _table_cells(lines[end])
                if len(cells) != expected_cells:
                    break
                end += 1

            if output and output[-1].strip():
                output.append("")
            output.extend(lines[index:end])
            if end < len(lines) and lines[end].strip():
                output.append("")
            index = end
            continue

        output.append(line)
        index += 1

    return "\n".join(output)


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
    """Render sanitized Markdown HTML with automatic RTL/LTR message direction."""
    source = str(source or "")
    normalized = _normalize_table_spacing(source)
    parser = markdown.Markdown(extensions=_EXTENSIONS, output_format="html5")
    rendered = parser.convert(normalized)
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
