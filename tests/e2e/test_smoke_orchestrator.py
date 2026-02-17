"""E2E smoke tests for orchestrator-mode pipeline execution.

Tests the --via-orchestrator mode of scripts/smoke_test.py which routes
the full pipeline through the orchestrator's POST /run endpoint instead
of calling each service directly.

Category A tests: orchestrator HTTP layer only (no downstream services needed).
Category B tests: full pipeline via orchestrator (all 6 services required).

Usage:
    pytest tests/e2e/test_smoke_orchestrator.py -m e2e -v
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

# Ensure the project root is importable
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from shared.db import init_db, transaction
from shared.server import BaseService
from services.orchestrator.main import OrchestratorHandler
from services.orchestrator.pipeline import PipelineRunner
from scripts.smoke_test import (
    SmokeReport,
    check_all_services,
    run_smoke_test_via_orchestrator,
)

pytestmark = pytest.mark.e2e


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _http_get(url: str, timeout: int = 5) -> dict:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _http_post(url: str, data: dict, timeout: int = 30) -> dict:
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def orchestrator_server(tmp_path):
    """Start a real orchestrator HTTP server with a temp DB.

    Downstream services are NOT running — only tests orchestrator HTTP layer.
    """
    db_path = tmp_path / "test_orch.db"
    init_db(db_path)

    # Seed test data
    with transaction(str(db_path)) as conn:
        conn.execute(
            "INSERT INTO papers (arxiv_id, title, stage) VALUES (?, ?, ?)",
            ("2401.00001", "Test Paper Alpha", "discovered"),
        )
        conn.execute(
            "INSERT INTO papers (arxiv_id, title, stage) VALUES (?, ?, ?)",
            ("2401.00002", "Test Paper Beta", "analyzed"),
        )

    port = _get_free_port()
    runner = PipelineRunner(str(db_path))
    OrchestratorHandler.runner = runner

    service = BaseService("orchestrator", port, OrchestratorHandler, str(db_path))
    thread = threading.Thread(target=service.run, daemon=True)
    thread.start()
    time.sleep(0.3)

    yield {"port": port, "db_path": str(db_path), "service": service}

    if service.server:
        service.server.shutdown()
    OrchestratorHandler.runner = None
    OrchestratorHandler._routes = None


# ---------------------------------------------------------------------------
# Category A: Orchestrator HTTP layer (no downstream services)
# ---------------------------------------------------------------------------


class TestOrchestratorSmokeUnit:
    """Tests that only need the orchestrator HTTP server, not downstream services."""

    def test_health_returns_ok(self, orchestrator_server):
        port = orchestrator_server["port"]
        data = _http_get(f"http://localhost:{port}/health")

        assert data["status"] == "ok"
        assert data["service"] == "orchestrator"
        assert "uptime_seconds" in data

    def test_services_status_structure(self, orchestrator_server):
        port = orchestrator_server["port"]
        data = _http_get(f"http://localhost:{port}/status/services")

        assert "all_healthy" in data
        assert len(data["services"]) == 5
        for name in ("discovery", "analyzer", "extractor", "validator", "codegen"):
            assert name in data["services"]
            assert "port" in data["services"][name]

    def test_status_returns_pipeline_state(self, orchestrator_server):
        port = orchestrator_server["port"]
        data = _http_get(f"http://localhost:{port}/status")

        assert data["papers_by_stage"]["discovered"] == 1
        assert data["papers_by_stage"]["analyzed"] == 1

    def test_run_returns_valid_response(self, orchestrator_server):
        """POST /run returns a well-formed response regardless of service availability."""
        port = orchestrator_server["port"]
        data = _http_post(
            f"http://localhost:{port}/run",
            {"query": "test:query", "stages": 1},
        )

        assert data["run_id"].startswith("run-")
        assert data["status"] in ("completed", "partial", "failed")
        assert "time_ms" in data
        assert isinstance(data["stages_completed"], int)

    def test_run_with_paper_id_resolves_stages(self, orchestrator_server):
        """POST /run with paper_id of a 'discovered' paper should try analyzer next."""
        port = orchestrator_server["port"]
        db_path = orchestrator_server["db_path"]

        # Get paper_id for the 'discovered' paper
        import sqlite3

        con = sqlite3.connect(db_path)
        paper_id = con.execute(
            "SELECT id FROM papers WHERE arxiv_id = '2401.00001'"
        ).fetchone()[0]
        con.close()

        data = _http_post(
            f"http://localhost:{port}/run",
            {"paper_id": paper_id, "stages": 1},
        )

        # Will fail because analyzer is not running, but should attempt it
        assert data["run_id"].startswith("run-")
        assert "analyzer" in data.get("results", {}) or len(data["errors"]) > 0


# ---------------------------------------------------------------------------
# Category B: Full E2E (requires all 6 services running)
# ---------------------------------------------------------------------------


def _all_services_available() -> bool:
    """Check if all pipeline services + orchestrator are running."""
    try:
        health = check_all_services()
        if not all(health.values()):
            return False
        req = urllib.request.Request(
            "http://localhost:8775/health", method="GET"
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            return data.get("status") == "ok"
    except Exception:
        return False


@pytest.mark.slow
@pytest.mark.skipif(
    not _all_services_available(),
    reason="All 6 services (ports 8770-8775) must be running",
)
class TestOrchestratorSmokeE2E:
    """Full E2E tests requiring all 6 pipeline services running."""

    @pytest.fixture(scope="class")
    def orchestrator_report(self) -> SmokeReport:
        """Run the smoke test via orchestrator once and share across tests."""
        return run_smoke_test_via_orchestrator()

    def test_final_stage_is_codegen(self, orchestrator_report: SmokeReport):
        assert orchestrator_report.final_stage == "codegen", (
            f"Expected 'codegen', got '{orchestrator_report.final_stage}'"
        )

    def test_pipeline_passed(self, orchestrator_report: SmokeReport):
        assert orchestrator_report.passed is True

    def test_formulas_extracted(self, orchestrator_report: SmokeReport):
        assert orchestrator_report.formulas_extracted > 0

    def test_code_generated(self, orchestrator_report: SmokeReport):
        assert orchestrator_report.codegen_count > 0

    def test_orchestrator_step_present(self, orchestrator_report: SmokeReport):
        """The report should include an 'orchestrator' step with the /run response."""
        orch_steps = [
            s for s in orchestrator_report.steps if s.service == "orchestrator"
        ]
        assert len(orch_steps) >= 1
        orch = orch_steps[-1]
        assert orch.response is not None
        assert orch.response.get("run_id", "").startswith("run-")

    def test_timing_reasonable(self, orchestrator_report: SmokeReport):
        assert orchestrator_report.total_elapsed_s < 1800, (
            f"Pipeline took {orchestrator_report.total_elapsed_s:.0f}s (>30 min)"
        )
