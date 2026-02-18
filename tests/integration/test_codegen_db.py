"""Integration tests for Codegen service — real SQLite DB, mocked LLM."""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.request
from unittest.mock import patch

from shared.db import transaction
from services.codegen.main import (
    CodegenHandler,
    _mark_formula_failed,
    _query_formulas,
    _store_generated_code,
    _update_formula_description,
    _update_formula_stage,
)
from shared.server import BaseService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_formula(db_path: str, paper_id: int = 1, latex: str = "x^2",
                    stage: str = "validated") -> int:
    """Insert a formula and return its id."""
    with transaction(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO formulas (paper_id, latex, latex_hash, context, stage) "
            "VALUES (?, ?, ?, ?, ?)",
            (paper_id, latex, f"hash_{latex}_{stage}", "test context", stage),
        )
        fid: int = cursor.lastrowid  # type: ignore[assignment]
        return fid


# ===========================================================================
# _query_formulas Tests
# ===========================================================================


class TestQueryFormulas:
    """Tests for _query_formulas() with real SQLite."""

    def test_query_validated_formulas(self, validated_formula_db):
        db = str(validated_formula_db)
        formulas = _query_formulas(db, None, None, 50, False)
        assert len(formulas) == 1
        assert formulas[0]["stage"] == "validated"

    def test_query_by_paper_id(self, validated_formula_db):
        db = str(validated_formula_db)
        formulas = _query_formulas(db, paper_id=1, formula_id=None,
                                   max_formulas=50, force=False)
        assert len(formulas) == 1
        assert formulas[0]["paper_id"] == 1

    def test_query_by_paper_id_no_match(self, validated_formula_db):
        db = str(validated_formula_db)
        formulas = _query_formulas(db, paper_id=999, formula_id=None,
                                   max_formulas=50, force=False)
        assert len(formulas) == 0

    def test_query_by_formula_id(self, validated_formula_db):
        db = str(validated_formula_db)
        formulas = _query_formulas(db, None, formula_id=1,
                                   max_formulas=50, force=False)
        assert len(formulas) == 1
        assert formulas[0]["id"] == 1

    def test_query_force_includes_codegen(self, validated_formula_db):
        db = str(validated_formula_db)
        # Change formula stage to codegen
        with transaction(db) as conn:
            conn.execute("UPDATE formulas SET stage='codegen' WHERE id=1")

        # Without force: no results
        formulas = _query_formulas(db, None, None, 50, False)
        assert len(formulas) == 0

        # With force: found
        formulas = _query_formulas(db, None, None, 50, True)
        assert len(formulas) == 1

    def test_query_respects_limit(self, validated_formula_db):
        db = str(validated_formula_db)
        for i in range(5):
            _insert_formula(db, paper_id=1, latex=f"formula_{i}")

        formulas = _query_formulas(db, None, None, 3, False)
        assert len(formulas) == 3

    def test_query_empty_db(self, initialized_db):
        formulas = _query_formulas(str(initialized_db), None, None, 50, False)
        assert len(formulas) == 0

    def test_query_joins_paper_title(self, validated_formula_db):
        db = str(validated_formula_db)
        formulas = _query_formulas(db, None, None, 50, False)
        assert len(formulas) == 1
        assert "paper_title" in formulas[0]
        assert formulas[0]["paper_title"] is not None


# ===========================================================================
# _store_generated_code Tests
# ===========================================================================


class TestStoreGeneratedCode:
    """Tests for _store_generated_code() — write to generated_code table."""

    def test_store_code_row(self, validated_formula_db):
        db = str(validated_formula_db)
        _store_generated_code(
            db, 1, "python", "x**2 + 1",
            {"function_name": "formula_1", "variables": ["x"]}, None,
        )

        with transaction(db) as conn:
            rows = conn.execute(
                "SELECT * FROM generated_code WHERE formula_id=1"
            ).fetchall()
        assert len(rows) == 1
        assert rows[0]["language"] == "python"
        assert rows[0]["code"] == "x**2 + 1"
        meta = json.loads(rows[0]["metadata"])
        assert meta["function_name"] == "formula_1"

    def test_store_overwrites_existing(self, validated_formula_db):
        """Re-generation overwrites previous code for same formula+language."""
        db = str(validated_formula_db)
        _store_generated_code(db, 1, "c99", "old_code", None, None)
        _store_generated_code(db, 1, "c99", "new_code", None, None)

        with transaction(db) as conn:
            rows = conn.execute(
                "SELECT * FROM generated_code "
                "WHERE formula_id=1 AND language='c99'"
            ).fetchall()
        assert len(rows) == 1
        assert rows[0]["code"] == "new_code"

    def test_store_with_error(self, validated_formula_db):
        db = str(validated_formula_db)
        _store_generated_code(db, 1, "rust", "", None, "codegen failed")

        with transaction(db) as conn:
            row = conn.execute(
                "SELECT * FROM generated_code "
                "WHERE formula_id=1 AND language='rust'"
            ).fetchone()
        assert row["error"] == "codegen failed"
        assert row["code"] == ""

    def test_store_multiple_languages(self, validated_formula_db):
        db = str(validated_formula_db)
        for lang in ("c99", "rust", "python"):
            _store_generated_code(db, 1, lang, f"code_{lang}", None, None)

        with transaction(db) as conn:
            rows = conn.execute(
                "SELECT * FROM generated_code WHERE formula_id=1"
            ).fetchall()
        assert len(rows) == 3


# ===========================================================================
# _update_formula_description Tests
# ===========================================================================


class TestUpdateFormulaDescription:
    """Tests for _update_formula_description()."""

    def test_updates_description(self, validated_formula_db):
        db = str(validated_formula_db)
        desc = json.dumps({"explanation": "Test explanation", "domain": "math"})
        _update_formula_description(db, 1, desc)

        with transaction(db) as conn:
            row = conn.execute(
                "SELECT description FROM formulas WHERE id=1"
            ).fetchone()
        stored = json.loads(row["description"])
        assert stored["explanation"] == "Test explanation"


# ===========================================================================
# _update_formula_stage Tests
# ===========================================================================


class TestUpdateFormulaStage:
    """Tests for _update_formula_stage()."""

    def test_updates_to_codegen(self, validated_formula_db):
        db = str(validated_formula_db)
        _update_formula_stage(db, 1)

        with transaction(db) as conn:
            row = conn.execute(
                "SELECT stage FROM formulas WHERE id=1"
            ).fetchone()
        assert row["stage"] == "codegen"


# ===========================================================================
# _mark_formula_failed Tests
# ===========================================================================


class TestMarkFormulaFailed:
    """Tests for _mark_formula_failed()."""

    def test_marks_failed_with_error(self, validated_formula_db):
        db = str(validated_formula_db)
        _mark_formula_failed(db, 1, "codegen: all languages failed")

        with transaction(db) as conn:
            row = conn.execute(
                "SELECT stage, error FROM formulas WHERE id=1"
            ).fetchone()
        assert row["stage"] == "failed"
        assert "codegen" in row["error"]


# ===========================================================================
# HTTP Endpoint Tests
# ===========================================================================


def _get_free_port() -> int:
    """Get a free TCP port."""
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class TestProcessEndpoint:
    """Tests for POST /process via real HTTP server, mocked LLM."""

    def _start_server(self, db_path: str):
        """Start codegen service on a random port."""
        port = _get_free_port()
        CodegenHandler.ollama_url = "http://localhost:11434"
        CodegenHandler.max_formulas_default = 50

        service = BaseService("codegen", port, CodegenHandler, db_path)
        thread = threading.Thread(target=service.run, daemon=True)
        thread.start()
        time.sleep(0.3)
        return port

    def test_process_empty_formulas(self, initialized_db):
        """No formulas → success with zero counts."""
        db = str(initialized_db)
        port = self._start_server(db)

        req = urllib.request.Request(
            f"http://localhost:{port}/process",
            data=json.dumps({}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read())

        assert body["success"] is True
        assert body["formulas_processed"] == 0
        assert body["code_generated"] == {"c99": 0, "rust": 0, "python": 0}

    @patch("services.codegen.main.explain_formulas_batch", return_value={})
    def test_process_with_formula_no_explanation(
        self, mock_batch, validated_formula_db
    ):
        """Process formula with failed explanation — codegen still succeeds."""
        db = str(validated_formula_db)
        port = self._start_server(db)

        req = urllib.request.Request(
            f"http://localhost:{port}/process",
            data=json.dumps({}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())

        assert body["success"] is True
        assert body["formulas_processed"] == 1
        assert body["explanations_generated"] == 0
        # Code should still be generated
        assert body["code_generated"]["python"] >= 1

    @patch("services.codegen.main.explain_formulas_batch", return_value={
        1: {
            "explanation": "Test",
            "variables": [],
            "assumptions": [],
            "domain": "math",
        }
    })
    def test_process_with_explanation(self, mock_batch, validated_formula_db):
        """Full process with successful explanation."""
        db = str(validated_formula_db)
        port = self._start_server(db)

        req = urllib.request.Request(
            f"http://localhost:{port}/process",
            data=json.dumps({}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())

        assert body["success"] is True
        assert body["formulas_processed"] == 1
        assert body["explanations_generated"] == 1

        # Verify DB state
        with transaction(db) as conn:
            formula = conn.execute(
                "SELECT stage, description FROM formulas WHERE id=1"
            ).fetchone()
            gen_code = conn.execute(
                "SELECT * FROM generated_code WHERE formula_id=1"
            ).fetchall()

        assert formula["stage"] == "codegen"
        assert formula["description"] is not None
        assert len(gen_code) == 3  # c99, rust, python

    @patch("services.codegen.main.explain_formulas_batch", return_value={})
    def test_process_specific_paper(self, mock_batch, validated_formula_db):
        """Process formulas for a specific paper_id."""
        db = str(validated_formula_db)
        port = self._start_server(db)

        req = urllib.request.Request(
            f"http://localhost:{port}/process",
            data=json.dumps({"paper_id": 1}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())

        assert body["success"] is True
        assert body["formulas_processed"] == 1

    @patch("services.codegen.main.explain_formulas_batch", return_value={})
    def test_process_nonexistent_paper(self, mock_batch, validated_formula_db):
        """Process with nonexistent paper_id returns 0 processed."""
        db = str(validated_formula_db)
        port = self._start_server(db)

        req = urllib.request.Request(
            f"http://localhost:{port}/process",
            data=json.dumps({"paper_id": 999}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read())

        assert body["success"] is True
        assert body["formulas_processed"] == 0
