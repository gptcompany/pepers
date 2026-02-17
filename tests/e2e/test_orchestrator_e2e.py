"""E2E tests for orchestrator — real HTTP server, real DB, no mocks."""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.request

import pytest

from shared.db import init_db, transaction
from shared.server import BaseService
from services.orchestrator.main import OrchestratorHandler
from services.orchestrator.pipeline import PipelineRunner

pytestmark = pytest.mark.e2e


def _get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture
def e2e_orchestrator(tmp_path):
    """Start a real orchestrator server with a temp DB."""
    db_path = tmp_path / "e2e_orchestrator.db"
    init_db(db_path)

    # Seed with test data
    with transaction(str(db_path)) as conn:
        conn.execute(
            "INSERT INTO papers (arxiv_id, title, stage) VALUES (?, ?, ?)",
            ("2401.00001", "Kelly Criterion E2E Paper", "discovered"),
        )
        conn.execute(
            "INSERT INTO papers (arxiv_id, title, stage) VALUES (?, ?, ?)",
            ("2401.00002", "Optimal Betting E2E Paper", "analyzed"),
        )

    port = _get_free_port()
    runner = PipelineRunner(str(db_path))
    OrchestratorHandler.runner = runner

    service = BaseService(
        "orchestrator", port, OrchestratorHandler, str(db_path)
    )
    thread = threading.Thread(target=service.run, daemon=True)
    thread.start()
    time.sleep(0.3)

    yield {"port": port, "db_path": str(db_path), "service": service}

    if service.server:
        service.server.shutdown()
    OrchestratorHandler.runner = None
    OrchestratorHandler._routes = None


class TestOrchestratorE2E:
    """End-to-end tests with real HTTP server."""

    def test_health(self, e2e_orchestrator):
        port = e2e_orchestrator["port"]
        resp = urllib.request.urlopen(f"http://localhost:{port}/health")
        data = json.loads(resp.read())

        assert data["status"] == "ok"
        assert data["service"] == "orchestrator"
        assert "uptime_seconds" in data

    def test_status_returns_pipeline_state(self, e2e_orchestrator):
        port = e2e_orchestrator["port"]
        resp = urllib.request.urlopen(f"http://localhost:{port}/status")
        data = json.loads(resp.read())

        assert data["papers_by_stage"]["discovered"] == 1
        assert data["papers_by_stage"]["analyzed"] == 1
        assert data["cron"]["enabled"] is False

    def test_status_services_reports_downstream(self, e2e_orchestrator):
        port = e2e_orchestrator["port"]
        resp = urllib.request.urlopen(f"http://localhost:{port}/status/services")
        data = json.loads(resp.read())

        assert "all_healthy" in data
        assert len(data["services"]) == 5
        for name, info in data["services"].items():
            assert "port" in info

    def test_run_returns_valid_structure(self, e2e_orchestrator):
        """POST /run returns well-formed response."""
        port = e2e_orchestrator["port"]

        # Use paper_id with a seeded paper to avoid slow arXiv API calls
        body = json.dumps({"paper_id": 1, "stages": 1}).encode()
        req = urllib.request.Request(
            f"http://localhost:{port}/run",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=30)
        data = json.loads(resp.read())

        assert data["run_id"].startswith("run-")
        assert data["status"] in ("completed", "partial", "failed")
        assert "time_ms" in data
        assert isinstance(data["stages_completed"], int)
