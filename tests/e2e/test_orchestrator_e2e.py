"""E2E tests for orchestrator — real HTTP server, real DB, no mocks."""

from __future__ import annotations

import json
import time
import urllib.request
import urllib.error

import pytest

pytestmark = pytest.mark.e2e


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

    def test_run_returns_async_202(self, e2e_orchestrator):
        """POST /run returns HTTP 202 with run_id, poll GET /runs for result."""
        port = e2e_orchestrator["port"]

        # Use paper_id with a seeded paper to avoid slow arXiv API calls
        body = json.dumps({"paper_id": 1, "stages": 1}).encode()
        req = urllib.request.Request(
            f"http://localhost:{port}/run",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=30)

        # Async: expect 202
        assert resp.status == 202
        data = json.loads(resp.read())
        assert data["run_id"].startswith("run-")
        assert data["status"] == "running"

        # Poll for completion (handle 404 race: record not yet created)
        run_id = data["run_id"]
        deadline = time.time() + 30
        result = None
        while time.time() < deadline:
            try:
                poll_resp = urllib.request.urlopen(
                    f"http://localhost:{port}/runs?id={run_id}", timeout=5
                )
                result = json.loads(poll_resp.read())
                if result.get("status") != "running":
                    break
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise
            time.sleep(0.5)

        assert result is not None
        assert result["status"] in ("completed", "partial", "failed")
        assert isinstance(result["stages_completed"], int)
