"""Unit tests for expand_custom_notations() in latex.py."""

from __future__ import annotations

import pytest

from services.extractor.latex import expand_custom_notations


def _formula(latex: str) -> dict:
    """Create a minimal formula dict."""
    return {"latex": latex, "formula_type": "equation", "start": 0, "end": len(latex)}


class TestExpandCustomNotations:
    """Tests for expand_custom_notations()."""

    def test_no_notations_passthrough(self):
        """Empty notations list returns formulas unchanged."""
        formulas = [_formula(r"\alpha + \beta")]
        result = expand_custom_notations(formulas, [])
        assert result == formulas

    def test_zero_arg_macro(self):
        """0-arg macro is expanded correctly."""
        notations = [{"name": "R", "body": r"\mathbb{R}", "nargs": 0}]
        formulas = [_formula(r"x \in \R")]
        result = expand_custom_notations(formulas, notations)
        assert result[0]["latex"] == r"x \in \mathbb{R}"

    def test_zero_arg_macro_no_false_match(self):
        """0-arg macro does not match longer command names."""
        notations = [{"name": "R", "body": r"\mathbb{R}", "nargs": 0}]
        formulas = [_formula(r"\Rightarrow x")]
        result = expand_custom_notations(formulas, notations)
        assert result[0]["latex"] == r"\Rightarrow x"

    def test_one_arg_macro(self):
        """1-arg macro is expanded correctly."""
        notations = [
            {"name": "Expect", "body": r"\mathbb{E}\left[#1\right]", "nargs": 1}
        ]
        formulas = [_formula(r"\Expect{X}")]
        result = expand_custom_notations(formulas, notations)
        assert result[0]["latex"] == r"\mathbb{E}\left[X\right]"

    def test_two_arg_macro(self):
        """2-arg macro is expanded correctly."""
        notations = [
            {"name": "KL", "body": r"D_{\mathrm{KL}}\left(#1 \| #2\right)", "nargs": 2}
        ]
        formulas = [_formula(r"\KL{P}{Q}")]
        result = expand_custom_notations(formulas, notations)
        assert result[0]["latex"] == r"D_{\mathrm{KL}}\left(P \| Q\right)"

    def test_macro_not_in_formula(self):
        """Macro not present in formula — no change."""
        notations = [
            {"name": "Expect", "body": r"\mathbb{E}\left[#1\right]", "nargs": 1}
        ]
        formulas = [_formula(r"\alpha + \beta")]
        result = expand_custom_notations(formulas, notations)
        assert result[0]["latex"] == r"\alpha + \beta"

    def test_multiple_occurrences(self):
        """Same macro expanded multiple times in one formula."""
        notations = [
            {"name": "Var", "body": r"\mathrm{Var}\left(#1\right)", "nargs": 1}
        ]
        formulas = [_formula(r"\Var{X} + \Var{Y}")]
        result = expand_custom_notations(formulas, notations)
        assert result[0]["latex"] == r"\mathrm{Var}\left(X\right) + \mathrm{Var}\left(Y\right)"

    def test_multiple_notations(self):
        """Multiple notations applied in sequence."""
        notations = [
            {"name": "E", "body": r"\mathbb{E}\left[#1\right]", "nargs": 1},
            {"name": "Var", "body": r"\mathrm{Var}\left(#1\right)", "nargs": 1},
        ]
        formulas = [_formula(r"\E{X} + \Var{X}")]
        result = expand_custom_notations(formulas, notations)
        assert result[0]["latex"] == (
            r"\mathbb{E}\left[X\right] + \mathrm{Var}\left(X\right)"
        )

    def test_original_not_modified(self):
        """Original formula dicts are not mutated."""
        notations = [{"name": "R", "body": r"\mathbb{R}", "nargs": 0}]
        original = _formula(r"x \in \R")
        original_latex = original["latex"]
        expand_custom_notations([original], notations)
        assert original["latex"] == original_latex

    def test_preserves_other_fields(self):
        """Non-latex fields are preserved in output."""
        notations = [{"name": "R", "body": r"\mathbb{R}", "nargs": 0}]
        formulas = [{"latex": r"\R", "formula_type": "display", "start": 5, "end": 10}]
        result = expand_custom_notations(formulas, notations)
        assert result[0]["formula_type"] == "display"
        assert result[0]["start"] == 5
        assert result[0]["end"] == 10

    def test_multiple_formulas(self):
        """All formulas in list are processed."""
        notations = [{"name": "R", "body": r"\mathbb{R}", "nargs": 0}]
        formulas = [_formula(r"x \in \R"), _formula(r"y \in \R^n")]
        result = expand_custom_notations(formulas, notations)
        assert len(result) == 2
        assert result[0]["latex"] == r"x \in \mathbb{R}"
        assert result[1]["latex"] == r"y \in \mathbb{R}^n"

    def test_nargs_default_zero(self):
        """Missing nargs key defaults to 0."""
        notations = [{"name": "R", "body": r"\mathbb{R}"}]
        formulas = [_formula(r"x \in \R")]
        result = expand_custom_notations(formulas, notations)
        assert result[0]["latex"] == r"x \in \mathbb{R}"
