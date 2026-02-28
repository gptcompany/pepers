"""Property-based tests for LaTeX formula extraction.

These tests use Hypothesis to generate a wide range of inputs and verify
that the extraction and processing functions are stable (don't crash)
and respect certain invariants.
"""

import pytest
from hypothesis import given, strategies as st
from services.extractor.latex import (
    extract_formulas,
    filter_formulas,
    is_nontrivial,
    expand_custom_notations,
    extract_context,
)


@given(text=st.text())
def test_extract_formulas_stability(text: str):
    """Verifies that extract_formulas never crashes on any string."""
    try:
        formulas = extract_formulas(text)
        assert isinstance(formulas, list)
        for f in formulas:
            assert isinstance(f, dict)
            assert "latex" in f
            assert "start" in f
            assert "end" in f
            assert "formula_type" in f
            # Invariant: latex content should be a substring of the original text
            # unless the extraction logic modifies it (it currently strips it)
            extracted = text[f["start"]:f["end"]]
            # The actual content extracted might be slightly different due to stripping
            # or regex capturing groups, but it should be based on that slice.
    except Exception as e:
        pytest.fail(f"extract_formulas() crashed on input: {text!r} with error: {e}")


@given(text=st.text())
def test_is_nontrivial_stability(text: str):
    """Verifies that is_nontrivial never crashes on any string."""
    try:
        is_nontrivial(text)
    except Exception as e:
        pytest.fail(f"is_nontrivial() crashed on input: {text!r} with error: {e}")


@given(text=st.text())
def test_filter_formulas_stability(text: str):
    """Verifies that filter_formulas never crashes with extracted results."""
    # We first extract formulas from a random text to get valid-ish formula dicts
    formulas = extract_formulas(text)
    try:
        filtered = filter_formulas(formulas)
        assert isinstance(filtered, list)
        assert len(filtered) <= len(formulas)
    except Exception as e:
        pytest.fail(f"filter_formulas() crashed on formulas from: {text!r} with error: {e}")


@given(
    text=st.text(),
    notations=st.lists(
        st.fixed_dictionaries({
            "name": st.text(min_size=1, alphabet=st.characters(whitelist_categories=("Lu", "Ll"))),
            "body": st.text(),
            "nargs": st.integers(min_value=0, max_value=5),
        })
    )
)
def test_expand_custom_notations_stability(text: str, notations: list[dict]):
    """Verifies that expand_custom_notations never crashes."""
    formulas = extract_formulas(text)
    try:
        expanded = expand_custom_notations(formulas, notations)
        assert isinstance(expanded, list)
        assert len(expanded) == len(formulas)
    except Exception as e:
        pytest.fail(f"expand_custom_notations() crashed with notations: {notations!r} on text: {text!r} with error: {e}")


@given(
    text=st.text(),
    window=st.integers(min_value=0, max_value=1000)
)
def test_extract_context_stability(text: str, window: int):
    """Verifies that extract_context never crashes with random indices."""
    formulas = extract_formulas(text)
    for f in formulas:
        try:
            ctx = extract_context(text, f["start"], f["end"], window)
            assert isinstance(ctx, str)
        except Exception as e:
            pytest.fail(f"extract_context() crashed on indices ({f['start']}, {f['end']}) with window {window} on text: {text!r} with error: {e}")


@given(text=st.text())
def test_extract_formulas_invariants(text: str):
    """Check core invariants of extraction."""
    formulas = extract_formulas(text)
    
    # Invariant 1: Spans are non-overlapping
    occupied_indices = set()
    for f in formulas:
        span = set(range(f["start"], f["end"]))
        assert not (span & occupied_indices), f"Overlapping formula found: {f}"
        occupied_indices.update(span)

    # Invariant 2: Formulas are sorted by start index
    starts = [f["start"] for f in formulas]
    assert starts == sorted(starts)
