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

        # Services not running in E2E, so all should be error
        assert data["all_healthy"] is False
        assert len(data["services"]) == 5
        for name, info in data["services"].items():
            assert info["status"] == "error"
            assert "port" in info

    def test_run_with_no_services_returns_errors(self, e2e_orchestrator):
        """POST /run when downstream services are not running."""
        port = e2e_orchestrator["port"]

        body = json.dumps({"query": "test", "stages": 1}).encode()
        req = urllib.request.Request(
            f"http://localhost:{port}/run",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req)
        data = json.loads(resp.read())

        # Should return a result but with errors (services not running)
        assert data["run_id"].startswith("run-")
        assert data["status"] in ("partial", "failed")
        assert len(data["errors"]) > 0

    def test_run_batch_mode(self, e2e_orchestrator):
        """POST /run without query or paper_id (batch mode)."""
        port = e2e_orchestrator["port"]

        body = json.dumps({"stages": 2}).encode()
        req = urllib.request.Request(
            f"http://localhost:{port}/run",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req)
        data = json.loads(resp.read())

        assert "run_id" in data
        assert "time_ms" in data
        assert isinstance(data["time_ms"], int)
