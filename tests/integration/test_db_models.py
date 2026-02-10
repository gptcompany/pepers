"""Integration tests: Pydantic models <-> SQLite database round-trip."""

from __future__ import annotations

import json

import pytest

from shared.db import get_connection, transaction
from shared.models import Formula, GeneratedCode, Paper, PipelineStage, Validation


@pytest.mark.integration
class TestPaperRoundTrip:
    """Test Paper model <-> SQLite INSERT/SELECT round-trip."""

    def test_insert_and_read_minimal(self, initialized_db):
        with transaction(initialized_db) as conn:
            conn.execute(
                "INSERT INTO papers (arxiv_id, title, stage) VALUES (?, ?, ?)",
                ("2401.00001", "Test Paper", "discovered"),
            )
        conn = get_connection(initialized_db)
        row = conn.execute(
            "SELECT * FROM papers WHERE arxiv_id=?", ("2401.00001",)
        ).fetchone()
        paper = Paper.model_validate(dict(row))
        assert paper.arxiv_id == "2401.00001"
        assert paper.title == "Test Paper"
        assert paper.stage == PipelineStage.DISCOVERED
        assert paper.authors == []
        conn.close()

    def test_insert_and_read_with_json_fields(self, initialized_db):
        authors = json.dumps(["Alice Smith", "Bob Jones"])
        categories = json.dumps(["q-fin.PM", "stat.ML"])
        crossref = json.dumps({"publisher": "Springer", "type": "journal-article"})

        with transaction(initialized_db) as conn:
            conn.execute(
                """INSERT INTO papers (arxiv_id, title, abstract, authors, categories,
                   crossref_data, stage, score)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "2401.00002", "Full Paper", "Abstract text",
                    authors, categories, crossref, "analyzed", 0.85,
                ),
            )

        conn = get_connection(initialized_db)
        row = conn.execute(
            "SELECT * FROM papers WHERE arxiv_id=?", ("2401.00002",)
        ).fetchone()
        paper = Paper.model_validate(dict(row))
        assert paper.authors == ["Alice Smith", "Bob Jones"]
        assert paper.categories == ["q-fin.PM", "stat.ML"]
        assert paper.crossref_data is not None
        assert paper.crossref_data["publisher"] == "Springer"
        assert paper.score == 0.85
        conn.close()

    def test_insert_with_sample_fixture(self, initialized_db, sample_paper_row):
        with transaction(initialized_db) as conn:
            cols = ", ".join(sample_paper_row.keys())
            placeholders = ", ".join("?" * len(sample_paper_row))
            conn.execute(
                f"INSERT INTO papers ({cols}) VALUES ({placeholders})",
                list(sample_paper_row.values()),
            )

        conn = get_connection(initialized_db)
        row = conn.execute("SELECT * FROM papers LIMIT 1").fetchone()
        paper = Paper.model_validate(dict(row))
        assert paper.arxiv_id == "2401.00001"
        assert paper.authors == ["Alice Smith", "Bob Jones"]
        conn.close()


@pytest.mark.integration
class TestFormulaRoundTrip:
    """Test Formula model <-> SQLite round-trip."""

    def test_insert_and_read(self, initialized_db):
        with transaction(initialized_db) as conn:
            conn.execute(
                "INSERT INTO papers (arxiv_id, title, stage) VALUES (?, ?, ?)",
                ("2401.00001", "Test", "discovered"),
            )
        with transaction(initialized_db) as conn:
            conn.execute(
                "INSERT INTO formulas (paper_id, latex, latex_hash, stage) "
                "VALUES (?, ?, ?, ?)",
                (1, r"f^* = \frac{p}{a}", "abc123hash", "extracted"),
            )

        conn = get_connection(initialized_db)
        row = conn.execute("SELECT * FROM formulas LIMIT 1").fetchone()
        formula = Formula.model_validate(dict(row))
        assert formula.paper_id == 1
        assert formula.latex == r"f^* = \frac{p}{a}"
        assert formula.latex_hash == "abc123hash"
        conn.close()

    def test_foreign_key_constraint(self, initialized_db):
        with pytest.raises(Exception):
            with transaction(initialized_db) as conn:
                conn.execute(
                    "INSERT INTO formulas (paper_id, latex, latex_hash, stage) "
                    "VALUES (?, ?, ?, ?)",
                    (9999, "x^2", "hash", "extracted"),
                )


@pytest.mark.integration
class TestValidationRoundTrip:
    """Test Validation model <-> SQLite round-trip."""

    def test_insert_and_read(self, initialized_db):
        with transaction(initialized_db) as conn:
            conn.execute(
                "INSERT INTO papers (arxiv_id, title, stage) VALUES (?, ?, ?)",
                ("2401.00001", "Test", "discovered"),
            )
        with transaction(initialized_db) as conn:
            conn.execute(
                "INSERT INTO formulas (paper_id, latex, latex_hash, stage) "
                "VALUES (?, ?, ?, ?)",
                (1, "x^2", "hash", "extracted"),
            )
        with transaction(initialized_db) as conn:
            conn.execute(
                "INSERT INTO validations (formula_id, engine, is_valid, result, time_ms) "
                "VALUES (?, ?, ?, ?, ?)",
                (1, "sympy", 1, "Valid", 150),
            )

        conn = get_connection(initialized_db)
        row = conn.execute("SELECT * FROM validations LIMIT 1").fetchone()
        v = Validation.model_validate(dict(row))
        assert v.engine == "sympy"
        assert v.is_valid == True  # noqa: E712 — SQLite stores as INTEGER 1
        assert v.time_ms == 150
        conn.close()


@pytest.mark.integration
class TestGeneratedCodeRoundTrip:
    """Test GeneratedCode model <-> SQLite round-trip."""

    def test_insert_and_read(self, initialized_db):
        with transaction(initialized_db) as conn:
            conn.execute(
                "INSERT INTO papers (arxiv_id, title, stage) VALUES (?, ?, ?)",
                ("2401.00001", "Test", "discovered"),
            )
        with transaction(initialized_db) as conn:
            conn.execute(
                "INSERT INTO formulas (paper_id, latex, latex_hash, stage) "
                "VALUES (?, ?, ?, ?)",
                (1, "x^2", "hash", "extracted"),
            )
        metadata = json.dumps({"compiler": "sympy", "version": "1.12"})
        with transaction(initialized_db) as conn:
            conn.execute(
                "INSERT INTO generated_code (formula_id, language, code, metadata, stage) "
                "VALUES (?, ?, ?, ?, ?)",
                (1, "python", "x = sympy.Symbol('x')", metadata, "codegen"),
            )

        conn = get_connection(initialized_db)
        row = conn.execute("SELECT * FROM generated_code LIMIT 1").fetchone()
        gc = GeneratedCode.model_validate(dict(row))
        assert gc.language == "python"
        assert gc.metadata == {"compiler": "sympy", "version": "1.12"}
        conn.close()


@pytest.mark.integration
class TestFullPipelineFlow:
    """Test a complete paper -> formula -> validation -> codegen flow."""

    def test_complete_flow(self, initialized_db):
        with transaction(initialized_db) as conn:
            conn.execute(
                """INSERT INTO papers (arxiv_id, title, abstract, authors,
                   categories, stage, score)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    "2401.00001", "Kelly Criterion", "Kelly paper abstract",
                    json.dumps(["Kelly, J.L."]), json.dumps(["q-fin.PM"]),
                    "discovered", None,
                ),
            )

        with transaction(initialized_db) as conn:
            conn.execute(
                "INSERT INTO formulas (paper_id, latex, latex_hash, stage) "
                "VALUES (?, ?, ?, ?)",
                (1, r"f^* = \frac{p}{a} - \frac{q}{b}", "kelly_hash", "extracted"),
            )

        with transaction(initialized_db) as conn:
            conn.execute(
                "INSERT INTO validations (formula_id, engine, is_valid, result, time_ms) "
                "VALUES (?, ?, ?, ?, ?)",
                (1, "maxima", 1, "Valid expression", 230),
            )

        with transaction(initialized_db) as conn:
            conn.execute(
                "INSERT INTO generated_code (formula_id, language, code, metadata, stage) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    1, "python", "def kelly(p, a, q, b): return p/a - q/b",
                    json.dumps({"method": "direct"}), "codegen",
                ),
            )

        conn = get_connection(initialized_db)

        paper = Paper.model_validate(
            dict(conn.execute("SELECT * FROM papers LIMIT 1").fetchone())
        )
        assert paper.arxiv_id == "2401.00001"
        assert paper.authors == ["Kelly, J.L."]

        formula = Formula.model_validate(
            dict(conn.execute("SELECT * FROM formulas LIMIT 1").fetchone())
        )
        assert formula.paper_id == paper.id

        validation = Validation.model_validate(
            dict(conn.execute("SELECT * FROM validations LIMIT 1").fetchone())
        )
        assert validation.formula_id == formula.id
        assert validation.is_valid == True  # noqa: E712

        code = GeneratedCode.model_validate(
            dict(conn.execute("SELECT * FROM generated_code LIMIT 1").fetchone())
        )
        assert code.formula_id == formula.id
        assert "kelly" in code.code

        conn.close()
