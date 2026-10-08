from utils.math_parser import format_response_math, parse_math


def test_latex_symbols():
    value = parse_math(r"\sigma(x) = \frac{1}{1 + e^{-x}}")
    assert "σ(x)" in value
    assert "⁻ˣ" in value
    assert "⁄" in value


def test_math_operators_and_limits():
    value = parse_math(r"x \to +\infty, x \ge 0, y \approx 1")
    assert value == "x → +∞, x ≥ 0, y ≈ 1"


def test_sqrt_and_scripts():
    value = parse_math(r"\sqrt{x^2 + y_2}")
    assert "√(" in value
    assert "x²" in value
    assert "y₂" in value


def test_inline_code_is_preserved():
    tick = chr(96)
    value = format_response_math(tick + r"\sigma(x)" + tick + " and $" + r"\sigma(x)" + "$")
    assert value == tick + r"\sigma(x)" + tick + " and σ(x)"


def test_fenced_code_is_preserved():
    fence = chr(96) * 3
    source = fence + "python\nprint(r'" + r"\sigma" + "')\n" + fence
    assert format_response_math(source) == source
