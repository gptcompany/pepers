"""Integration tests for Validator service — real SQLite DB, mock CAS HTTP."""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.request
from unittest.mock import MagicMock, patch

import pytest

from shared.db import transaction
from services.validator.cas_client import CASServiceError, EngineResult
from services.validator.consensus import ConsensusOutcome
from services.validator.main import (
    ValidatorHandler,
    _mark_formula_failed,
    _query_formulas,
    _store_validations,
    _update_formula_stage,
)
from services.validator.consensus import ConsensusResult
from shared.server import BaseService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_formula(db_path: str, paper_id: int = 1, latex: str = "x^2",
                    stage: str = "extracted", **kwargs) -> int:
    """Insert a formula and return its id."""
    with transaction(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO formulas (paper_id, latex, latex_hash, stage) "
            "VALUES (?, ?, ?, ?)",
            (paper_id, latex, f"hash_{latex}", stage),
        )
        return cursor.lastrowid


# ===========================================================================
# _query_formulas Tests
# ===========================================================================


class TestQueryFormulas:
    """Tests for _query_formulas() with real SQLite."""

    def test_query_extracted_formulas(self, extracted_formula_db):
        db = str(extracted_formula_db)
        formulas = _query_formulas(db, None, None, 50, False)
        assert len(formulas) == 1
        assert formulas[0]["stage"] == "extracted"

    def test_query_by_paper_id(self, extracted_formula_db):
        db = str(extracted_formula_db)
        formulas = _query_formulas(db, paper_id=1, formula_id=None,
                                   max_formulas=50, force=False)
        assert len(formulas) == 1
        assert formulas[0]["paper_id"] == 1

    def test_query_by_paper_id_no_match(self, extracted_formula_db):
        db = str(extracted_formula_db)
        formulas = _query_formulas(db, paper_id=999, formula_id=None,
                                   max_formulas=50, force=False)
        assert len(formulas) == 0

    def test_query_by_formula_id(self, extracted_formula_db):
        db = str(extracted_formula_db)
        formulas = _query_formulas(db, None, formula_id=1,
                                   max_formulas=50, force=False)
        assert len(formulas) == 1
        assert formulas[0]["id"] == 1

    def test_query_force_includes_validated(self, extracted_formula_db):
        db = str(extracted_formula_db)
        # Change formula stage to validated
        with transaction(db) as conn:
            conn.execute("UPDATE formulas SET stage='validated' WHERE id=1")

        # Without force: no results
        formulas = _query_formulas(db, None, None, 50, False)
        assert len(formulas) == 0

        # With force: found
        formulas = _query_formulas(db, None, None, 50, True)
        assert len(formulas) == 1

    def test_query_respects_limit(self, extracted_formula_db):
        db = str(extracted_formula_db)
        # Insert more formulas
        for i in range(5):
            _insert_formula(db, paper_id=1, latex=f"formula_{i}")

        formulas = _query_formulas(db, None, None, 3, False)
        assert len(formulas) == 3

    def test_query_empty_db(self, initialized_db):
        formulas = _query_formulas(str(initialized_db), None, None, 50, False)
        assert len(formulas) == 0


# ===========================================================================
# _store_validations Tests
# ===========================================================================


class TestStoreValidations:
    """Tests for _store_validations() — write to validations table."""

    def test_store_engine_results(self, extracted_formula_db):
        db = str(extracted_formula_db)
        results = [
            EngineResult(engine="sympy", success=True, is_valid=True,
                         simplified="x+1", time_ms=50),
            EngineResult(engine="maxima", success=True, is_valid=True,
                         simplified="x+1", time_ms=100),
        ]
        _store_validations(db, 1, results)

        with transaction(db) as conn:
            rows = conn.execute(
                "SELECT * FROM validations WHERE formula_id=1"
            ).fetchall()
        assert len(rows) == 2
        engines = {r["engine"] for r in rows}
        assert engines == {"sympy", "maxima"}

    def test_store_overwrites_existing(self, extracted_formula_db):
        """Re-validation overwrites previous results for same formula+engine."""
        db = str(extracted_formula_db)
        results_v1 = [
            EngineResult(engine="sympy", success=True, is_valid=False,
                         simplified="wrong", time_ms=50),
        ]
        _store_validations(db, 1, results_v1)

        results_v2 = [
            EngineResult(engine="sympy", success=True, is_valid=True,
                         simplified="correct", time_ms=30),
        ]
        _store_validations(db, 1, results_v2)

        with transaction(db) as conn:
            rows = conn.execute(
                "SELECT * FROM validations WHERE formula_id=1 AND engine='sympy'"
            ).fetchall()
        assert len(rows) == 1
        assert rows[0]["result"] == "correct"
        assert rows[0]["is_valid"] == 1

    def test_store_error_result(self, extracted_formula_db):
        """Engine errors are stored with error field."""
        db = str(extracted_formula_db)
        results = [
            EngineResult(engine="maxima", success=False,
                         error="timeout", time_ms=10000),
        ]
        _store_validations(db, 1, results)

        with transaction(db) as conn:
            row = conn.execute(
                "SELECT * FROM validations WHERE formula_id=1"
            ).fetchone()
        assert row["error"] == "timeout"
        assert row["is_valid"] is None


# ===========================================================================
# _update_formula_stage Tests
# ===========================================================================


class TestUpdateFormulaStage:
    """Tests for _update_formula_stage()."""

    def test_valid_updates_to_validated(self, extracted_formula_db):
        db = str(extracted_formula_db)
        consensus = ConsensusResult(
            outcome=ConsensusOutcome.VALID, detail="ok",
            engine_count=2, agree_count=2,
        )
        _update_formula_stage(db, 1, consensus)

        with transaction(db) as conn:
            row = conn.execute("SELECT stage FROM formulas WHERE id=1").fetchone()
        assert row["stage"] == "validated"

    def test_invalid_updates_to_validated(self, extracted_formula_db):
        db = str(extracted_formula_db)
        consensus = ConsensusResult(
            outcome=ConsensusOutcome.INVALID, detail="invalid",
            engine_count=2, agree_count=2,
        )
        _update_formula_stage(db, 1, consensus)

        with transaction(db) as conn:
            row = conn.execute("SELECT stage FROM formulas WHERE id=1").fetchone()
        assert row["stage"] == "validated"

    def test_partial_updates_to_validated(self, extracted_formula_db):
        db = str(extracted_formula_db)
        consensus = ConsensusResult(
            outcome=ConsensusOutcome.PARTIAL, detail="partial",
            engine_count=2, agree_count=1,
        )
        _update_formula_stage(db, 1, consensus)

        with transaction(db) as conn:
            row = conn.execute("SELECT stage FROM formulas WHERE id=1").fetchone()
        assert row["stage"] == "validated"

    def test_unparseable_no_change(self, extracted_formula_db):
        """UNPARSEABLE leaves stage as 'extracted'."""
        db = str(extracted_formula_db)
        consensus = ConsensusResult(
            outcome=ConsensusOutcome.UNPARSEABLE, detail="unparseable",
            engine_count=2, agree_count=0,
        )
        _update_formula_stage(db, 1, consensus)

        with transaction(db) as conn:
            row = conn.execute("SELECT stage FROM formulas WHERE id=1").fetchone()
        assert row["stage"] == "extracted"


# ===========================================================================
# _mark_formula_failed Tests
# ===========================================================================


class TestMarkFormulaFailed:
    """Tests for _mark_formula_failed()."""

    def test_marks_failed_with_error(self, extracted_formula_db):
        db = str(extracted_formula_db)
        _mark_formula_failed(db, 1, "CAS timeout")

        with transaction(db) as conn:
            row = conn.execute(
                "SELECT stage, error FROM formulas WHERE id=1"
            ).fetchone()
        assert row["stage"] == "failed"
        assert "CAS timeout" in row["error"]
        assert row["error"].startswith("validator:")


# ===========================================================================
# HTTP Endpoint Tests
# ===========================================================================


def _get_free_port() -> int:
    """Get a free TCP port."""
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class TestProcessEndpoint:
    """Tests for POST /process via real HTTP server."""

    def _start_server(self, db_path: str, cas_url: str = "http://mock:8769"):
        """Start validator service on a random port."""
        port = _get_free_port()
        ValidatorHandler.cas_url = cas_url
        ValidatorHandler.max_formulas_default = 50
        ValidatorHandler.engines = ["sympy", "maxima"]

        service = BaseService("validator", port, ValidatorHandler, db_path)
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

    def test_process_cas_unhealthy(self, extracted_formula_db):
        """CAS service down → 503 error."""
        import urllib.error as urlerr

        db = str(extracted_formula_db)
        port = self._start_server(db)

        # Mock CAS health to return False
        with patch.object(
            __import__("services.validator.cas_client", fromlist=["CASClient"]).CASClient,
            "health", return_value=False,
        ):
            req = urllib.request.Request(
                f"http://localhost:{port}/process",
                data=json.dumps({}).encode(),
                headers={"Content-Type": "application/json"},
            )
            with pytest.raises(urlerr.HTTPError) as exc_info:
                urllib.request.urlopen(req, timeout=5)

            assert exc_info.value.code == 503

    def test_process_success_with_mock_cas(self, extracted_formula_db):
        """Full flow with mock CAS returning valid results."""
        db = str(extracted_formula_db)

        mock_cas_response = MagicMock()
        mock_cas_response.results = [
            EngineResult(engine="sympy", success=True, is_valid=True,
                         simplified="p/a - q/b", time_ms=50),
            EngineResult(engine="maxima", success=True, is_valid=True,
                         simplified="p/a - q/b", time_ms=100),
        ]
        mock_cas_response.latex_preprocessed = r"f^* = \frac{p}{a} - \frac{q}{b}"
        mock_cas_response.time_ms = 150

        port = self._start_server(db)

        with patch.object(
            __import__("services.validator.cas_client", fromlist=["CASClient"]).CASClient,
            "health", return_value=True,
        ), patch.object(
            __import__("services.validator.cas_client", fromlist=["CASClient"]).CASClient,
            "validate", return_value=mock_cas_response,
        ):
            req = urllib.request.Request(
                f"http://localhost:{port}/process",
                data=json.dumps({}).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = json.loads(resp.read())

        assert body["success"] is True
        assert body["formulas_processed"] == 1
        assert body["formulas_valid"] == 1

        # Verify DB was updated
        with transaction(db) as conn:
            formula = conn.execute(
                "SELECT stage FROM formulas WHERE id=1"
            ).fetchone()
            validations = conn.execute(
                "SELECT * FROM validations WHERE formula_id=1"
            ).fetchall()

        assert formula["stage"] == "validated"
        assert len(validations) == 2
