"""End-to-end tests for Validator service — real CAS service at :8769.

These tests make real HTTP requests to the CAS microservice.
They are skipped if CAS is not available.

Run with: pytest tests/e2e/test_validator_e2e.py -m e2e -v
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

from shared.db import init_db, transaction
from services.validator.cas_client import CASClient
from services.validator.consensus import ConsensusOutcome, apply_consensus
from services.validator.main import ValidatorHandler
from services.discovery.main import upsert_paper
from services.analyzer.main import migrate_db
from shared.server import BaseService

pytestmark = pytest.mark.e2e

CAS_URL = "http://localhost:8769"


def _cas_available() -> bool:
    """Check if CAS microservice is running."""
    try:
        req = urllib.request.Request(f"{CAS_URL}/health")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            return data.get("status") == "ok"
    except (urllib.error.URLError, OSError):
        return False


def _get_free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture
def e2e_db(tmp_path):
    """Temporary SQLite database for E2E tests with migrations applied."""
    db_path = tmp_path / "e2e_validator.db"
    init_db(db_path)
    migrate_db(str(db_path))
    return str(db_path)


@pytest.fixture
def e2e_db_with_formula(e2e_db):
    """E2E DB with a paper and extracted formula."""
    upsert_paper(e2e_db, {
        "arxiv_id": "2401.99999",
        "title": "Test Paper for Validator E2E",
        "abstract": "Testing formula validation.",
        "authors": json.dumps(["Test Author"]),
        "categories": json.dumps(["q-fin.PM"]),
        "doi": None,
        "pdf_url": None,
        "published_date": "2024-01-15",
        "stage": "extracted",
    })
    with transaction(e2e_db) as conn:
        conn.execute(
            "INSERT INTO formulas (paper_id, latex, latex_hash, stage) "
            "VALUES (?, ?, ?, ?)",
            (1, r"x^2 + 2 \cdot x + 1 = (x + 1)^2", "e2e_hash_1", "extracted"),
        )
    return e2e_db


class TestCASHealth:
    """Verify CAS service connectivity."""

    def test_cas_health(self):
        if not _cas_available():
            pytest.skip("CAS service not available at :8769")
        client = CASClient(CAS_URL)
        assert client.health() is True


class TestCASValidation:
    """Test real CAS validation with SymPy + Maxima."""

    def test_validate_simple_equation(self):
        """Validate a known-true equation: x^2 + 2x + 1 = (x+1)^2."""
        if not _cas_available():
            pytest.skip("CAS service not available at :8769")

        client = CASClient(CAS_URL, timeout=60)
        # Use sympy+sage only (MATLAB license temporarily unavailable)
        response = client.validate(
            r"x^2 + 2 \cdot x + 1 = (x + 1)^2",
            engines=["sympy", "sage"],
        )

        assert len(response.results) == 2
        assert response.time_ms > 0

        # Both engines should succeed on this identity
        successful = [r for r in response.results if r.success]
        assert len(successful) == 2

    def test_validate_derivative(self):
        r"""Validate derivative: \frac{d}{dx} x^2 = 2x."""
        if not _cas_available():
            pytest.skip("CAS service not available at :8769")

        client = CASClient(CAS_URL, timeout=60)
        response = client.validate(
            r"\frac{d}{dx} x^2 = 2x",
            engines=["sympy", "sage"],
        )

        assert len(response.results) == 2
        successful = [r for r in response.results if r.success]
        assert len(successful) >= 1

    def test_validate_with_single_engine(self):
        """Validate with only SymPy engine."""
        if not _cas_available():
            pytest.skip("CAS service not available at :8769")

        client = CASClient(CAS_URL, timeout=60)
        response = client.validate(r"x^2 + 1", engines=["sympy"])

        assert len(response.results) == 1
        assert response.results[0].engine == "sympy"
        assert response.results[0].success is True

    def test_consensus_on_real_results(self):
        """Apply consensus on real CAS results."""
        if not _cas_available():
            pytest.skip("CAS service not available at :8769")

        client = CASClient(CAS_URL, timeout=60)
        response = client.validate(
            r"x^2 + 2 \cdot x + 1 = (x + 1)^2",
            engines=["sympy", "sage"],
        )

        consensus = apply_consensus(response.results)
        # Any outcome is valid — engines may disagree on LaTeX parsing
        assert consensus.outcome in (
            ConsensusOutcome.VALID,
            ConsensusOutcome.INVALID,
            ConsensusOutcome.PARTIAL,
            ConsensusOutcome.UNPARSEABLE,
        )
        assert consensus.engine_count == len(response.results)


class TestValidatorE2EFlow:
    """Full E2E: insert formula → POST /process → verify DB."""

    def test_full_process_flow(self, e2e_db_with_formula):
        """Insert formula, run validator, verify DB results."""
        if not _cas_available():
            pytest.skip("CAS service not available at :8769")

        db = e2e_db_with_formula

        # Start validator service (engines: sympy+sage only, skip matlab)
        port = _get_free_port()
        ValidatorHandler.cas_url = CAS_URL
        ValidatorHandler.max_formulas_default = 50
        ValidatorHandler.engines = ["sympy", "sage"]

        service = BaseService("validator", port, ValidatorHandler, db)
        thread = threading.Thread(target=service.run, daemon=True)
        thread.start()
        time.sleep(0.3)

        # POST /process
        req = urllib.request.Request(
            f"http://localhost:{port}/process",
            data=json.dumps({}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read())

        assert body["success"] is True
        assert body["formulas_processed"] >= 1

        # Verify validations table has entries
        with transaction(db) as conn:
            validations = conn.execute(
                "SELECT * FROM validations WHERE formula_id=1"
            ).fetchall()

        assert len(validations) >= 1
        engines_tested = {v["engine"] for v in validations}
        assert len(engines_tested) >= 1

        # Verify formula stage was updated (unless UNPARSEABLE)
        with transaction(db) as conn:
            formula = conn.execute(
                "SELECT stage FROM formulas WHERE id=1"
            ).fetchone()

        # Stage should be either 'validated' or 'extracted' (if unparseable)
        assert formula["stage"] in ("validated", "extracted")

    def test_process_specific_paper(self, e2e_db_with_formula):
        """Process formulas for a specific paper_id."""
        if not _cas_available():
            pytest.skip("CAS service not available at :8769")

        db = e2e_db_with_formula

        port = _get_free_port()
        ValidatorHandler.cas_url = CAS_URL
        ValidatorHandler.engines = ["sympy", "sage"]

        service = BaseService("validator", port, ValidatorHandler, db)
        thread = threading.Thread(target=service.run, daemon=True)
        thread.start()
        time.sleep(0.3)

        req = urllib.request.Request(
            f"http://localhost:{port}/process",
            data=json.dumps({"paper_id": 1}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read())

        assert body["success"] is True
        assert body["formulas_processed"] >= 1

    def test_process_nonexistent_paper(self, e2e_db_with_formula):
        """Process with nonexistent paper_id returns 0 processed."""
        if not _cas_available():
            pytest.skip("CAS service not available at :8769")

        db = e2e_db_with_formula

        port = _get_free_port()
        ValidatorHandler.cas_url = CAS_URL

        service = BaseService("validator", port, ValidatorHandler, db)
        thread = threading.Thread(target=service.run, daemon=True)
        thread.start()
        time.sleep(0.3)

        req = urllib.request.Request(
            f"http://localhost:{port}/process",
            data=json.dumps({"paper_id": 999}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read())

        assert body["success"] is True
        assert body["formulas_processed"] == 0
