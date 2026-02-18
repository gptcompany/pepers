"""End-to-end tests for Codegen service — real SymPy + optional Ollama.

These tests use real SymPy code generation (no mocks).
LLM tests are skipped if Ollama is not available.

Run with: pytest tests/e2e/test_codegen_e2e.py -m e2e -v
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
from services.codegen.generators import generate_all
from services.codegen.main import CodegenHandler
from services.discovery.main import upsert_paper
from services.analyzer.main import migrate_db
from shared.server import BaseService

pytestmark = pytest.mark.e2e

OLLAMA_URL = "http://localhost:11434"


def _ollama_available() -> bool:
    """Check if Ollama is running."""
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/tags")
        with urllib.request.urlopen(req, timeout=5):
            return True
    except (urllib.error.URLError, OSError):
        return False


def _get_free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture
def e2e_db(tmp_path):
    """Temporary SQLite database for E2E tests with migrations applied."""
    db_path = tmp_path / "e2e_codegen.db"
    init_db(db_path)
    migrate_db(str(db_path))
    return str(db_path)


@pytest.fixture
def e2e_db_with_formula(e2e_db):
    """E2E DB with a paper and validated formula."""
    upsert_paper(e2e_db, {
        "arxiv_id": "2401.99999",
        "title": "Test Paper for Codegen E2E",
        "abstract": "Testing code generation.",
        "authors": json.dumps(["Test Author"]),
        "categories": json.dumps(["q-fin.PM"]),
        "doi": None,
        "pdf_url": None,
        "published_date": "2024-01-15",
        "stage": "validated",
    })
    with transaction(e2e_db) as conn:
        conn.execute(
            "INSERT INTO formulas (paper_id, latex, latex_hash, context, stage) "
            "VALUES (?, ?, ?, ?, ?)",
            (1, r"f^* = \frac{p}{a} - \frac{q}{b}",
             "e2e_codegen_hash_1",
             "Kelly criterion optimal bet fraction",
             "validated"),
        )
    return e2e_db


# ===========================================================================
# Real SymPy Code Generation Tests
# ===========================================================================


class TestRealCodegen:
    """Test real SymPy code generation (no mocks)."""

    def test_kelly_formula(self):
        """Generate code for Kelly criterion formula."""
        results = generate_all(r"\frac{p}{a} - \frac{q}{b}", 1)
        assert len(results) == 3

        for r in results:
            assert r["error"] is None, f"{r['language']}: {r['error']}"
            assert r["code"], f"{r['language']} has empty code"

        # Verify variables
        for r in results:
            assert set(r["metadata"]["variables"]) == {"a", "b", "p", "q"}

    def test_polynomial(self):
        """Generate code for polynomial: x^2 + 2x + 1."""
        results = generate_all(r"x^2 + 2 x + 1", 2)
        for r in results:
            assert r["error"] is None, f"{r['language']}: {r['error']}"

    def test_simple_fraction(self):
        """Generate code for simple fraction: 1/2."""
        results = generate_all(r"\frac{1}{2}", 3)
        for r in results:
            assert r["error"] is None, f"{r['language']}: {r['error']}"

    def test_trig_function(self):
        """Generate code for trig function: sin(x)."""
        results = generate_all(r"\sin(x)", 4)
        for r in results:
            assert r["error"] is None, f"{r['language']}: {r['error']}"

    def test_sqrt(self):
        """Generate code for sqrt(x^2 + 1)."""
        results = generate_all(r"\sqrt{x^2 + 1}", 5)
        for r in results:
            assert r["error"] is None, f"{r['language']}: {r['error']}"

    def test_exponential(self):
        """Generate code for e^x."""
        results = generate_all(r"e^{x}", 6)
        for r in results:
            assert r["error"] is None, f"{r['language']}: {r['error']}"

    def test_multi_variable_complex(self):
        """Generate code for a more complex multi-variable formula."""
        results = generate_all(r"\frac{\mu - r}{\sigma^2}", 7)
        for r in results:
            assert r["error"] is None, f"{r['language']}: {r['error']}"


# ===========================================================================
# Real Ollama LLM Tests (skip if not available)
# ===========================================================================


class TestRealLLMExplanation:
    """Test real LLM explanation via Ollama."""

    def test_explain_kelly_formula(self):
        """Explain Kelly formula via real Ollama."""
        if not _ollama_available():
            pytest.skip("Ollama not available at :11434")

        from services.codegen.explain import explain_formula

        result = explain_formula(
            r"\frac{p}{a} - \frac{q}{b}",
            "Kelly criterion optimal fraction",
            "Kelly Criterion in Portfolio Optimization",
        )

        if result is None:
            pytest.skip("LLM returned no explanation (model may not be loaded)")

        assert "explanation" in result
        assert isinstance(result["explanation"], str)
        assert len(result["explanation"]) > 10


# ===========================================================================
# Full E2E HTTP Flow
# ===========================================================================


class TestCodegenE2EFlow:
    """Full E2E: insert validated formula → POST /process → verify DB."""

    def test_full_process_flow(self, e2e_db_with_formula):
        """Full flow with real SymPy, mocked LLM explanation."""
        from unittest.mock import patch

        db = e2e_db_with_formula

        port = _get_free_port()
        CodegenHandler.ollama_url = OLLAMA_URL
        CodegenHandler.max_formulas_default = 50

        service = BaseService("codegen", port, CodegenHandler, db)
        thread = threading.Thread(target=service.run, daemon=True)
        thread.start()
        time.sleep(0.3)

        # Mock LLM explanation to avoid network dependency
        with patch("services.codegen.main.explain_formulas_batch", return_value={}), \
             patch("services.codegen.main.explain_formula", return_value={
            "explanation": "E2E test explanation",
            "variables": [{"symbol": "p", "name": "probability",
                           "description": "win prob"}],
            "assumptions": ["Independent trials"],
            "domain": "mathematical finance",
        }):
            req = urllib.request.Request(
                f"http://localhost:{port}/process",
                data=json.dumps({}).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read())

        assert body["success"] is True
        assert body["formulas_processed"] == 1
        assert body["explanations_generated"] == 1
        assert body["code_generated"]["python"] >= 1

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
        desc = json.loads(formula["description"])
        assert desc["explanation"] == "E2E test explanation"

        assert len(gen_code) == 3
        languages = {row["language"] for row in gen_code}
        assert languages == {"c99", "rust", "python"}

        # Verify actual code was generated (not empty)
        for row in gen_code:
            assert row["code"], f"{row['language']} has empty code"

    def test_full_process_with_real_ollama(self, e2e_db_with_formula):
        """Full flow with real SymPy AND real Ollama."""
        if not _ollama_available():
            pytest.skip("Ollama not available at :11434")

        db = e2e_db_with_formula

        port = _get_free_port()
        CodegenHandler.ollama_url = OLLAMA_URL
        CodegenHandler.max_formulas_default = 50

        service = BaseService("codegen", port, CodegenHandler, db)
        thread = threading.Thread(target=service.run, daemon=True)
        thread.start()
        time.sleep(0.3)

        req = urllib.request.Request(
            f"http://localhost:{port}/process",
            data=json.dumps({}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read())

        assert body["success"] is True
        assert body["formulas_processed"] == 1
        # With real Ollama, code should always be generated
        assert body["code_generated"]["python"] >= 1
