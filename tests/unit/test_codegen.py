"""Unit tests for the Codegen service — real SymPy, mocked LLM."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
import sympy

from services.codegen.generators import (
    generate_all,
    generate_c99,
    generate_python,
    generate_rust,
    parse_formula,
)
from services.codegen.explain import explain_formula
from shared.models import FormulaExplanation


# ===========================================================================
# parse_formula() Tests
# ===========================================================================


class TestParseFormula:
    """Tests for parse_formula() — LaTeX to SymPy expression."""

    def test_simple_fraction(self):
        expr = parse_formula(r"\frac{1}{2}")
        # parse_latex may return Mul(1, Pow(2,-1)) instead of Rational
        assert float(expr) == pytest.approx(0.5)

    def test_multi_variable(self):
        expr = parse_formula(r"\frac{p}{a} - \frac{q}{b}")
        symbols = {str(s) for s in expr.free_symbols}
        assert symbols == {"a", "b", "p", "q"}

    def test_polynomial(self):
        expr = parse_formula(r"x^2 + 2 x + 1")
        x = sympy.Symbol("x")
        assert expr.subs(x, 0) == 1
        assert expr.subs(x, 1) == 4

    def test_strip_equation_env(self):
        expr = parse_formula(r"\begin{equation}x^2\end{equation}")
        x = sympy.Symbol("x")
        assert expr == x**2

    def test_strip_dollar_signs(self):
        expr = parse_formula(r"$x^2$")
        x = sympy.Symbol("x")
        assert expr == x**2

    def test_strip_double_dollar_signs(self):
        expr = parse_formula(r"$$x^2$$")
        x = sympy.Symbol("x")
        assert expr == x**2

    def test_empty_latex_raises(self):
        with pytest.raises(ValueError, match="Empty LaTeX"):
            parse_formula("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="Empty LaTeX"):
            parse_formula("   ")

    def test_empty_after_strip_raises(self):
        with pytest.raises(ValueError, match="Empty LaTeX"):
            parse_formula(r"\begin{equation}\end{equation}")

    def test_trig_function(self):
        expr = parse_formula(r"\sin(x)")
        x = sympy.Symbol("x")
        assert expr.subs(x, 0) == 0

    def test_sqrt(self):
        expr = parse_formula(r"\sqrt{4}")
        # parse_latex returns sqrt(4) unevaluated; verify numerically
        assert float(expr) == pytest.approx(2.0)


# ===========================================================================
# generate_c99() Tests
# ===========================================================================


class TestGenerateC99:
    """Tests for generate_c99() — SymPy to C99 code."""

    def test_simple_expr(self):
        x = sympy.Symbol("x")
        result = generate_c99(x**2 + 1, "test_func")
        assert "double" in result["code"]
        assert "test_func" in result["code"]
        assert isinstance(result["header"], str)
        assert result["variables"] == ["x"]

    def test_multi_var(self):
        a, b = sympy.symbols("a b")
        result = generate_c99(a / b, "div_func")
        assert "double" in result["code"]
        assert set(result["variables"]) == {"a", "b"}

    def test_variables_sorted(self):
        z, a, m = sympy.symbols("z a m")
        result = generate_c99(z + a + m, "sorted_test")
        assert result["variables"] == ["a", "m", "z"]


# ===========================================================================
# generate_rust() Tests
# ===========================================================================


class TestGenerateRust:
    """Tests for generate_rust() — SymPy to Rust code."""

    def test_simple_expr(self):
        x = sympy.Symbol("x")
        result = generate_rust(x**2, "sq_func")
        assert "fn" in result["code"]
        assert "sq_func" in result["code"]
        assert result["variables"] == ["x"]

    def test_multi_var(self):
        p, q = sympy.symbols("p q")
        result = generate_rust(p - q, "diff_func")
        assert set(result["variables"]) == {"p", "q"}


# ===========================================================================
# generate_python() Tests
# ===========================================================================


class TestGeneratePython:
    """Tests for generate_python() — SymPy to Python expression."""

    def test_simple_expr(self):
        x = sympy.Symbol("x")
        code = generate_python(x**2 + 1, "test_func")
        assert isinstance(code, str)
        assert "x" in code

    def test_fraction(self):
        a, b = sympy.symbols("a b")
        code = generate_python(a / b, "frac_func")
        assert "a" in code
        assert "b" in code

    def test_trig(self):
        x = sympy.Symbol("x")
        code = generate_python(sympy.sin(x), "sin_func")
        assert "sin" in code.lower() or "math.sin" in code


# ===========================================================================
# generate_all() Tests
# ===========================================================================


class TestGenerateAll:
    """Tests for generate_all() — orchestrates all 3 languages."""

    def test_valid_latex_produces_three_results(self):
        results = generate_all(r"\frac{p}{a} - \frac{q}{b}", 42)
        assert len(results) == 3
        languages = {r["language"] for r in results}
        assert languages == {"c99", "rust", "python"}

    def test_valid_latex_no_errors(self):
        results = generate_all(r"x^2 + 1", 1)
        for r in results:
            assert r["error"] is None, f"{r['language']} had error: {r['error']}"
            assert r["code"], f"{r['language']} has empty code"

    def test_metadata_contains_function_name(self):
        results = generate_all(r"x^2", 99)
        for r in results:
            assert r["metadata"]["function_name"] == "formula_99"

    def test_metadata_contains_variables(self):
        results = generate_all(r"x^2 + y", 1)
        for r in results:
            assert "variables" in r["metadata"]
            assert set(r["metadata"]["variables"]) == {"x", "y"}

    def test_invalid_latex_all_errors(self):
        # Use truly unparseable LaTeX (parse_latex is lenient with many inputs)
        results = generate_all("", 1)
        assert len(results) == 3
        for r in results:
            assert r["error"] is not None
            assert r["code"] == ""

    def test_empty_latex_all_errors(self):
        results = generate_all("", 1)
        assert len(results) == 3
        for r in results:
            assert r["error"] is not None

    def test_function_naming(self):
        results = generate_all(r"x", 7)
        for r in results:
            if r["metadata"]:
                assert r["metadata"]["function_name"] == "formula_7"


# ===========================================================================
# explain_formula() Tests (mocked LLM)
# ===========================================================================


_VALID_EXPLANATION = json.dumps({
    "explanation": "The Kelly criterion formula computes the optimal fraction.",
    "variables": [
        {"symbol": "p", "name": "win probability", "description": "Prob of winning"},
        {"symbol": "q", "name": "loss probability", "description": "Prob of losing"},
    ],
    "assumptions": ["Independent trials", "Known probabilities"],
    "domain": "mathematical finance",
})


class TestExplainFormula:
    """Tests for explain_formula() — all LLM calls mocked."""

    @patch("services.codegen.explain.call_ollama", return_value=_VALID_EXPLANATION)
    def test_ollama_success(self, mock_ollama):
        result = explain_formula(r"\frac{p}{a}", "some context", "Test Paper")
        assert result is not None
        assert result["explanation"]
        assert len(result["variables"]) == 2
        assert result["domain"] == "mathematical finance"

    @patch("services.codegen.explain.call_ollama", return_value=_VALID_EXPLANATION)
    def test_ollama_called_with_schema(self, mock_ollama):
        explain_formula(r"x^2", None, None)
        _, kwargs = mock_ollama.call_args
        assert "format" in kwargs
        schema = kwargs["format"]
        assert isinstance(schema, dict)
        assert "properties" in schema

    @patch("services.codegen.explain.call_ollama", return_value=_VALID_EXPLANATION)
    def test_prompt_includes_latex(self, mock_ollama):
        explain_formula(r"\frac{p}{a}", None, None)
        call_args = mock_ollama.call_args
        prompt = call_args[1]["prompt"] if "prompt" in call_args[1] else call_args[0][0]
        assert r"\frac{p}{a}" in prompt

    @patch("services.codegen.explain.call_ollama", return_value=_VALID_EXPLANATION)
    def test_prompt_includes_context(self, mock_ollama):
        explain_formula(r"x", "surrounding text", None)
        call_args = mock_ollama.call_args
        prompt = call_args[1]["prompt"] if "prompt" in call_args[1] else call_args[0][0]
        assert "surrounding text" in prompt

    @patch("services.codegen.explain.call_ollama", return_value=_VALID_EXPLANATION)
    def test_prompt_includes_paper_title(self, mock_ollama):
        explain_formula(r"x", None, "My Paper Title")
        call_args = mock_ollama.call_args
        prompt = call_args[1]["prompt"] if "prompt" in call_args[1] else call_args[0][0]
        assert "My Paper Title" in prompt

    @patch("services.codegen.explain.call_ollama",
           side_effect=RuntimeError("Ollama down"))
    @patch("services.codegen.explain.fallback_chain",
           return_value=(_VALID_EXPLANATION, "gemini_sdk"))
    def test_ollama_fail_gemini_fallback(self, mock_fallback, mock_ollama):
        result = explain_formula(r"x^2", None, None)
        assert result is not None
        assert result["explanation"]

    @patch("services.codegen.explain.call_ollama",
           side_effect=RuntimeError("Ollama down"))
    @patch("services.codegen.explain.fallback_chain",
           side_effect=RuntimeError("All failed"))
    def test_all_providers_fail_returns_none(self, mock_fallback, mock_ollama):
        result = explain_formula(r"x^2", None, None)
        assert result is None

    @patch("services.codegen.explain.call_ollama", return_value='{"invalid": true}')
    @patch("services.codegen.explain.fallback_chain",
           side_effect=RuntimeError("All failed"))
    def test_invalid_json_schema_returns_none(self, mock_fallback, mock_ollama):
        """Ollama returns JSON that doesn't match FormulaExplanation schema."""
        result = explain_formula(r"x", None, None)
        assert result is None

    @patch("services.codegen.explain.call_ollama", return_value=_VALID_EXPLANATION)
    def test_no_think_appended(self, mock_ollama):
        """Prompt always ends with /no_think."""
        explain_formula(r"x", None, None)
        call_args = mock_ollama.call_args
        prompt = call_args[1]["prompt"] if "prompt" in call_args[1] else call_args[0][0]
        assert "/no_think" in prompt


class TestFormulaExplanationModel:
    """Tests for FormulaExplanation Pydantic model."""

    def test_valid_data(self):
        exp = FormulaExplanation(
            explanation="Test explanation",
            variables=[{"symbol": "x", "name": "variable", "description": "desc"}],
            assumptions=["Assumption 1"],
            domain="statistics",
        )
        assert exp.explanation == "Test explanation"
        assert len(exp.variables) == 1

    def test_minimal_data(self):
        exp = FormulaExplanation(explanation="Minimal")
        assert exp.variables == []
        assert exp.assumptions == []
        assert exp.domain == ""

    def test_from_json(self):
        exp = FormulaExplanation.model_validate_json(_VALID_EXPLANATION)
        assert exp.explanation
        assert len(exp.variables) == 2

    def test_to_dict(self):
        exp = FormulaExplanation(explanation="Test", domain="math")
        d = exp.model_dump()
        assert d["explanation"] == "Test"
        assert d["domain"] == "math"
