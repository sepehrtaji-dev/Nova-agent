"""Dependency-free parser for common LaTeX-like mathematical notation."""

import re

_SYMBOLS = {
    r"\alpha": "α", r"\beta": "β", r"\gamma": "γ", r"\delta": "δ",
    r"\epsilon": "ε", r"\theta": "θ", r"\lambda": "λ", r"\mu": "μ",
    r"\pi": "π", r"\rho": "ρ", r"\sigma": "σ", r"\tau": "τ", r"\phi": "φ",
    r"\omega": "ω", r"\Gamma": "Γ", r"\Delta": "Δ", r"\Theta": "Θ",
    r"\Lambda": "Λ", r"\Pi": "Π", r"\Sigma": "Σ", r"\Omega": "Ω",
    r"\infty": "∞", r"\cdot": "·", r"\times": "×", r"\div": "÷",
    r"\pm": "±", r"\le": "≤", r"\leq": "≤", r"\ge": "≥", r"\geq": "≥",
    r"\neq": "≠", r"\ne": "≠", r"\approx": "≈", r"\sim": "∼",
    r"\to": "→", r"\rightarrow": "→", r"\leftarrow": "←",
    r"\Rightarrow": "⇒", r"\Leftrightarrow": "⇔",
    r"\in": "∈", r"\notin": "∉", r"\forall": "∀", r"\exists": "∃",
    r"\partial": "∂", r"\nabla": "∇", r"\sum": "Σ", r"\prod": "Π", r"\int": "∫",
    r"\ldots": "…", r"\cdots": "⋯", r"\quad": " ", r"\qquad": "  ", r"\,": " "
}

_SUPER_MAP = str.maketrans(
    "0123456789+-=()abcdefghijklmnopqrstuvwxyz",
    "⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺⁼⁽⁾ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖᑫʳˢᵗᵘᵛʷˣʸᶻ",
)
_SUB_MAP = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₋₊₌₍₎")

def _group(text, start):
    if start >= len(text) or text[start] != "{":
        return None, start
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i + 1
    return None, start

def _fragment(text):
    return parse_math(text).strip()

def parse_math(text):
    if not isinstance(text, str) or not text:
        return text
    value = text.replace(r"\[", "").replace(r"\]", "")
    value = value.replace(r"\(", "").replace(r"\)", "")
    value = value.replace("$$", "").replace("$", "")

    frac = re.compile(r"\\frac\s*(\{)")
    while True:
        match = frac.search(value)
        if not match:
            break
        numerator, end_num = _group(value, match.start(1))
        if numerator is None:
            break
        pos = end_num
        while pos < len(value) and value[pos].isspace():
            pos += 1
        denominator, end_den = _group(value, pos) if pos < len(value) else (None, pos)
        if denominator is None:
            break
        value = value[:match.start()] + "(" + _fragment(numerator) + ")⁄(" + _fragment(denominator) + ")" + value[end_den:]

    sqrt = re.compile(r"\\sqrt\s*(\{)")
    while True:
        match = sqrt.search(value)
        if not match:
            break
        inner, end = _group(value, match.start(1))
        if inner is None:
            break
        value = value[:match.start()] + "√(" + _fragment(inner) + ")" + value[end:]

    def script(match):
        marker = match.group(1)
        body = match.group(2)
        if body.startswith("{") and body.endswith("}"):
            body = body[1:-1]
        body = re.sub(r"\s+", "", body)
        return body.translate(_SUPER_MAP if marker == "^" else _SUB_MAP)

    value = re.sub(r"([_^])(\{[^{}]*\}|[A-Za-z0-9+\-=()])", script, value)
    for key in sorted(_SYMBOLS, key=len, reverse=True):
        value = value.replace(key, _SYMBOLS[key])
    value = re.sub(r"\\text\s*\{([^{}]*)\}", r"\1", value)
    value = re.sub(r"\\mathrm\s*\{([^{}]*)\}", r"\1", value)
    value = value.replace("->", "→").replace("<=", "≤").replace(">=", "≥")
    return re.sub(r"[ \t]{2,}", " ", value).strip()

def format_response_math(text):
    if not isinstance(text, str) or not text:
        return text
    tick = chr(96)
    pattern = "(" + re.escape(tick * 3) + r"[\s\S]*?" + re.escape(tick * 3) + "|" + re.escape(tick) + r"[^" + re.escape(tick) + r"\n]*" + re.escape(tick) + ")"
    parts = re.split(pattern, text)
    for i in range(0, len(parts), 2):
        parts[i] = parse_math(parts[i])
    return "".join(parts)