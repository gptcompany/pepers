"""E2E tests for custom notations: add notation → expand in extraction pipeline."""

from __future__ import annotations

import sqlite3

import pytest

from services.extractor.latex import (
    expand_custom_notations,
    extract_formulas,
    filter_formulas,
)
from shared.db import init_db, transaction


@pytest.mark.e2e
class TestNotationsE2E:
    """End-to-end: notations stored in DB are used to expand formulas."""

    @pytest.fixture
    def db_with_notations(self, tmp_path):
        """DB with schema initialized and custom notations inserted."""
        db_path = str(tmp_path / "e2e_notations.db")
        init_db(db_path)

        with transaction(db_path) as conn:
            conn.execute(
                "INSERT INTO custom_notations (name, body, nargs, description) "
                "VALUES (?, ?, ?, ?)",
                ("Expect", r"\mathbb{E}\left[#1\right]", 1, "Expected value"),
            )
            conn.execute(
                "INSERT INTO custom_notations (name, body, nargs, description) "
                "VALUES (?, ?, ?, ?)",
                ("Var", r"\mathrm{Var}\left(#1\right)", 1, "Variance"),
            )
            conn.execute(
                "INSERT INTO custom_notations (name, body, nargs, description) "
                "VALUES (?, ?, ?, ?)",
                ("R", r"\mathbb{R}", 0, "Real numbers"),
            )
        return db_path

    def test_full_pipeline_with_custom_macros(self, db_with_notations):
        """Extract formulas from markdown with custom macros → verify expansion."""
        markdown = r"""
# Test Paper

The expected return is $\Expect{X}$ for $X \in \R$.

The variance $\Var{Y}$ measures dispersion.

The key formula:
\begin{equation}
\Expect{R_p} = \sum_i w_i \Expect{R_i}
\end{equation}
"""
        # Step 1: Extract formulas
        raw = extract_formulas(markdown)
        filtered = filter_formulas(raw)

        # Step 2: Load notations from DB (simulating _load_notations)
        conn = sqlite3.connect(db_with_notations)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT name, body, nargs FROM custom_notations").fetchall()
        notations = [dict(r) for r in rows]
        conn.close()

        assert len(notations) == 3

        # Step 3: Expand
        expanded = expand_custom_notations(filtered, notations)

        # Verify: no \Expect, \Var, \R remain in expanded formulas
        for f in expanded:
            latex = f["latex"]
            # Custom macros should be replaced
            assert r"\Expect" not in latex, f"\\Expect not expanded in: {latex}"
            assert r"\Var" not in latex, f"\\Var not expanded in: {latex}"
            # \R should be expanded but \R in \Rightarrow etc should not be affected
            # Check that standalone \R is gone
            import re

            assert not re.search(
                r"\\R(?![a-zA-Z])", latex
            ), f"\\R not expanded in: {latex}"

    def test_no_notations_unchanged(self, tmp_path):
        """Without notations, formulas pass through unchanged."""
        db_path = str(tmp_path / "e2e_empty.db")
        init_db(db_path)

        markdown = r"""
## Formula
$$\alpha + \beta = \gamma$$
"""
        raw = extract_formulas(markdown)
        filtered = filter_formulas(raw)
        original_latex = [f["latex"] for f in filtered]

        expanded = expand_custom_notations(filtered, [])
        expanded_latex = [f["latex"] for f in expanded]

        assert original_latex == expanded_latex

    def test_notation_upsert_in_db(self, db_with_notations):
        """Verify upsert behavior: INSERT OR REPLACE keeps single row."""
        with transaction(db_with_notations) as conn:
            # Update existing notation
            conn.execute(
                "INSERT OR REPLACE INTO custom_notations "
                "(name, body, nargs, description, updated_at) "
                "VALUES (?, ?, ?, ?, datetime('now'))",
                ("Expect", r"\mathbb{E}[#1]", 1, "Updated"),
            )

        conn = sqlite3.connect(db_with_notations)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM custom_notations WHERE name = 'Expect'"
        ).fetchall()
        conn.close()

        assert len(rows) == 1
        assert rows[0]["body"] == r"\mathbb{E}[#1]"
        assert rows[0]["description"] == "Updated"
