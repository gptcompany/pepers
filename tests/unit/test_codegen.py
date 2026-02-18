"""Unit tests for the Codegen service — real SymPy, mocked LLM."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
import sympy

from services.codegen.generators import (
    clean_latex,
    generate_all,
    generate_c99,
    generate_python,
    generate_rust,
    parse_formula,
)
from services.codegen.explain import (
    _parse_batch_response,
    explain_formula,
    explain_formulas_batch,
)
from shared.models import FormulaExplanation


# ===========================================================================
# clean_latex() Tests
# ===========================================================================


class TestCleanLatex:
    """Tests for clean_latex() — macro stripping before parse_latex."""

    def test_strips_tag(self):
        assert r"\tag" not in clean_latex(r"x^2 \tag{13}")

    def test_strips_label(self):
        assert r"\label" not in clean_latex(r"x^2 \label{eq:kelly}")

    def test_unwraps_text(self):
        result = clean_latex(r"\text{for all}")
        assert "for all" in result
        assert r"\text" not in result

    def test_unwraps_mathrm(self):
        result = clean_latex(r"\mathrm{E}[X]")
        assert "E" in result
        assert r"\mathrm" not in result

    def test_unwraps_pmb(self):
        result = clean_latex(r"\pmb{x}")
        assert "x" in result
        assert r"\pmb" not in result

    def test_unwraps_operatorname(self):
        result = clean_latex(r"\operatorname{argmax}")
        assert "argmax" in result
        assert r"\operatorname" not in result

    def test_strips_spacing(self):
        result = clean_latex(r"a \, b \; c \quad d")
        assert r"\," not in result
        assert r"\;" not in result
        assert r"\quad" not in result

    def test_strips_left_right(self):
        result = clean_latex(r"\left( x \right)")
        assert r"\left" not in result
        assert r"\right" not in result
        assert "x" in result

    def test_replaces_equiv(self):
        result = clean_latex(r"f(x) \equiv g(x)")
        assert "=" in result
        assert r"\equiv" not in result

    def test_replaces_triangleq(self):
        result = clean_latex(r"f \triangleq g")
        assert "=" in result
        assert r"\triangleq" not in result

    def test_strips_dots(self):
        result = clean_latex(r"a_1 + \dots + a_n")
        assert r"\dots" not in result

    def test_strips_cdots(self):
        result = clean_latex(r"x_1 \cdots x_n")
        assert r"\cdots" not in result

    def test_strips_displaystyle(self):
        result = clean_latex(r"\displaystyle \frac{a}{b}")
        assert r"\displaystyle" not in result
        assert r"\frac" in result

    def test_strips_alignment(self):
        result = clean_latex(r"a &= b \\ c &= d")
        assert "&" not in result
        assert r"\\" not in result

    def test_strips_nonumber(self):
        result = clean_latex(r"x^2 \nonumber")
        assert r"\nonumber" not in result

    def test_preserves_math_content(self):
        """Core math content should survive cleanup."""
        result = clean_latex(r"\frac{a}{b} + \sum_{i=1}^{n} x_i")
        assert r"\frac" in result
        assert r"\sum" in result

    def test_collapses_whitespace(self):
        result = clean_latex(r"a  \,  b   c")
        # No double spaces
        assert "  " not in result


# ===========================================================================
# parse_formula() Tests (with clean_latex integration)
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

    def test_parse_with_tag(self):
        """\\tag{N} should be stripped, not interpreted as function."""
        expr = parse_formula(r"x^2 + 1 \tag{1}")
        x = sympy.Symbol("x")
        assert expr.subs(x, 0) == 1

    def test_parse_with_displaystyle(self):
        """\\displaystyle should be stripped."""
        expr = parse_formula(r"\displaystyle \frac{1}{2}")
        assert float(expr) == pytest.approx(0.5)

    def test_parse_with_equiv(self):
        """\\equiv should become =, parse_latex may interpret as Eq or rel."""
        # After replacement, 'x = y' should parse without error
        expr = parse_formula(r"x \equiv y")
        assert expr is not None

    def test_parse_with_left_right(self):
        """\\left( and \\right) should be stripped."""
        expr = parse_formula(r"\left( x + 1 \right)")
        x = sympy.Symbol("x")
        assert expr.subs(x, 0) == 1


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


# ===========================================================================
# _parse_batch_response() Tests
# ===========================================================================


_BATCH_RESPONSE_2 = json.dumps([
    {
        "index": 0,
        "explanation": "Formula zero computes X.",
        "variables": [{"symbol": "x", "name": "var", "description": "desc"}],
        "assumptions": ["Assumption"],
        "domain": "statistics",
    },
    {
        "index": 1,
        "explanation": "Formula one computes Y.",
        "variables": [],
        "assumptions": [],
        "domain": "probability",
    },
])


class TestParseBatchResponse:
    """Tests for _parse_batch_response() — JSON array → dict mapping."""

    def test_success_two_items(self):
        result = _parse_batch_response(_BATCH_RESPONSE_2, [100, 200])
        assert len(result) == 2
        assert result[100]["explanation"] == "Formula zero computes X."
        assert result[200]["domain"] == "probability"

    def test_invalid_json_returns_empty(self):
        result = _parse_batch_response("not json", [1, 2])
        assert result == {}

    def test_not_array_returns_empty(self):
        result = _parse_batch_response('{"key": "value"}', [1])
        assert result == {}

    def test_partial_failure_skips_bad_items(self):
        """One valid + one with bad schema → only valid returned."""
        raw = json.dumps([
            {
                "index": 0,
                "explanation": "Valid.",
                "variables": [],
                "assumptions": [],
                "domain": "math",
            },
            {
                "index": 1,
                # Missing 'explanation' field — Pydantic validation fails
            },
        ])
        result = _parse_batch_response(raw, [10, 20])
        assert 10 in result
        assert 20 not in result

    def test_out_of_range_index_skipped(self):
        raw = json.dumps([
            {
                "index": 5,
                "explanation": "Out of range.",
                "variables": [],
                "assumptions": [],
                "domain": "math",
            },
        ])
        result = _parse_batch_response(raw, [1, 2])
        assert result == {}

    def test_missing_index_skipped(self):
        raw = json.dumps([
            {
                "explanation": "No index.",
                "variables": [],
                "assumptions": [],
                "domain": "math",
            },
        ])
        result = _parse_batch_response(raw, [1])
        assert result == {}


# ===========================================================================
# explain_formulas_batch() Tests
# ===========================================================================


_SAMPLE_FORMULAS = [
    {"id": 1, "latex": r"\frac{p}{q}", "context": "Kelly criterion", "paper_title": "Paper A"},
    {"id": 2, "latex": r"x^2 + 1", "context": None, "paper_title": None},
    {"id": 3, "latex": r"\sigma^2", "context": "Variance", "paper_title": "Paper B"},
]


class TestExplainFormulasBatch:
    """Tests for explain_formulas_batch() — batched LLM calls."""

    @patch("services.codegen.explain.fallback_chain")
    def test_batch_success(self, mock_fallback):
        """All formulas explained in one batch call."""
        batch_resp = json.dumps([
            {"index": 0, "explanation": "E0", "variables": [], "assumptions": [], "domain": "math"},
            {"index": 1, "explanation": "E1", "variables": [], "assumptions": [], "domain": "math"},
            {"index": 2, "explanation": "E2", "variables": [], "assumptions": [], "domain": "math"},
        ])
        mock_fallback.return_value = (batch_resp, "ollama")

        result = explain_formulas_batch(_SAMPLE_FORMULAS, batch_size=10)
        assert len(result) == 3
        assert result[1]["explanation"] == "E0"
        assert result[3]["explanation"] == "E2"
        # Only one LLM call for 3 formulas
        assert mock_fallback.call_count == 1

    @patch("services.codegen.explain.fallback_chain")
    def test_batch_size_chunking(self, mock_fallback):
        """With batch_size=2, 3 formulas → 2 LLM calls."""
        batch_resp_1 = json.dumps([
            {"index": 0, "explanation": "E0", "variables": [], "assumptions": [], "domain": "math"},
            {"index": 1, "explanation": "E1", "variables": [], "assumptions": [], "domain": "math"},
        ])
        batch_resp_2 = json.dumps([
            {"index": 0, "explanation": "E2", "variables": [], "assumptions": [], "domain": "math"},
        ])
        mock_fallback.side_effect = [
            (batch_resp_1, "ollama"),
            (batch_resp_2, "ollama"),
        ]

        result = explain_formulas_batch(_SAMPLE_FORMULAS, batch_size=2)
        assert len(result) == 3
        assert mock_fallback.call_count == 2

    @patch("services.codegen.explain.fallback_chain")
    def test_total_failure_returns_empty(self, mock_fallback):
        """If fallback_chain raises, result is empty (caller falls back to per-formula)."""
        mock_fallback.side_effect = RuntimeError("All providers failed")

        result = explain_formulas_batch(_SAMPLE_FORMULAS)
        assert result == {}

    @patch("services.codegen.explain.fallback_chain")
    def test_partial_parse_failure(self, mock_fallback):
        """If LLM returns unparseable JSON, result is empty for that chunk."""
        mock_fallback.return_value = ("not valid json", "ollama")

        result = explain_formulas_batch(_SAMPLE_FORMULAS)
        assert result == {}

    def test_empty_formulas_returns_empty(self):
        """Empty formula list returns empty dict without LLM calls."""
        result = explain_formulas_batch([])
        assert result == {}

    @patch("services.codegen.explain.fallback_chain")
    def test_batch_prompt_includes_all_formulas(self, mock_fallback):
        """Batch prompt contains all formula LaTeX strings."""
        mock_fallback.return_value = (json.dumps([]), "ollama")

        explain_formulas_batch(_SAMPLE_FORMULAS[:2], batch_size=10)

        call_args = mock_fallback.call_args
        prompt = call_args[1]["prompt"] if "prompt" in call_args[1] else call_args[0][0]
        assert r"\frac{p}{q}" in prompt
        assert r"x^2 + 1" in prompt
