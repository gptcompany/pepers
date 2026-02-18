"""E2E tests for v11.0 features — async /run, GET /generated-code, GET /runs.

Uses a real orchestrator HTTP server with a temp DB. No mocks.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request

import pytest

from shared.db import transaction

pytestmark = pytest.mark.e2e

POLL_INTERVAL = 0.5
POLL_TIMEOUT = 30


def _poll_run(port: int, run_id: str) -> dict:
    """Poll GET /runs?id=xxx until status != running or timeout.

    Handles 404 during initial polling (race: record not yet created
    by the background thread).
    """
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        try:
            resp = urllib.request.urlopen(
                f"http://localhost:{port}/runs?id={run_id}", timeout=5
            )
            result = json.loads(resp.read())
            if result.get("status") != "running":
                return result
        except urllib.error.HTTPError as e:
            if e.code == 404:
                pass  # Record not yet persisted by background thread
            else:
                raise
        time.sleep(POLL_INTERVAL)
    raise AssertionError(f"Run {run_id} did not complete within {POLL_TIMEOUT}s")


# ---------------------------------------------------------------------------
# Async POST /run tests
# ---------------------------------------------------------------------------


class TestAsyncRun:
    """Tests for the async POST /run endpoint."""

    def test_async_run_returns_202_with_run_id(self, e2e_orchestrator):
        """POST /run returns HTTP 202 immediately with run_id."""
        port = e2e_orchestrator["port"]

        body = json.dumps({"paper_id": 1, "stages": 1}).encode()
        req = urllib.request.Request(
            f"http://localhost:{port}/run",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=10)

        assert resp.status == 202
        data = json.loads(resp.read())
        assert data["run_id"].startswith("run-")
        assert data["status"] == "running"

    def test_async_run_poll_completion(self, e2e_orchestrator):
        """POST /run → poll GET /runs?id=xxx → completed/partial/failed."""
        port = e2e_orchestrator["port"]

        body = json.dumps({"paper_id": 1, "stages": 1}).encode()
        req = urllib.request.Request(
            f"http://localhost:{port}/run",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=10)
        run_id = json.loads(resp.read())["run_id"]

        result = _poll_run(port, run_id)
        assert result["status"] in ("completed", "partial", "failed")
        assert isinstance(result["stages_completed"], int)
        assert result["completed_at"] is not None

    def test_async_run_invalid_stages_zero(self, e2e_orchestrator):
        """POST /run with stages=0 returns HTTP 400."""
        port = e2e_orchestrator["port"]

        body = json.dumps({"stages": 0}).encode()
        req = urllib.request.Request(
            f"http://localhost:{port}/run",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req, timeout=10)
        assert exc_info.value.code == 400

    def test_async_run_invalid_stages_six(self, e2e_orchestrator):
        """POST /run with stages=6 returns HTTP 400."""
        port = e2e_orchestrator["port"]

        body = json.dumps({"stages": 6}).encode()
        req = urllib.request.Request(
            f"http://localhost:{port}/run",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req, timeout=10)
        assert exc_info.value.code == 400

    def test_async_run_invalid_paper_id_string(self, e2e_orchestrator):
        """POST /run with paper_id="abc" returns HTTP 400."""
        port = e2e_orchestrator["port"]

        body = json.dumps({"paper_id": "abc"}).encode()
        req = urllib.request.Request(
            f"http://localhost:{port}/run",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req, timeout=10)
        assert exc_info.value.code == 400


# ---------------------------------------------------------------------------
# GET /generated-code tests
# ---------------------------------------------------------------------------


def _seed_generated_code(db_path: str) -> int:
    """Seed DB with formulas + generated code, return paper_id."""
    with transaction(db_path) as conn:
        # Paper already seeded by fixture (id=1)
        latex = r"f^* = \frac{p}{a} - \frac{q}{b}"
        latex_hash = hashlib.sha256(latex.encode()).hexdigest()
        conn.execute(
            "INSERT INTO formulas (paper_id, latex, latex_hash, stage) "
            "VALUES (?, ?, ?, ?)",
            (1, latex, latex_hash, "codegen"),
        )
        formula_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        conn.execute(
            "INSERT INTO generated_code (formula_id, language, code) "
            "VALUES (?, ?, ?)",
            (formula_id, "python", "def kelly(p, a, q, b): return p/a - q/b"),
        )
        conn.execute(
            "INSERT INTO generated_code (formula_id, language, code) "
            "VALUES (?, ?, ?)",
            (formula_id, "rust", "fn kelly(p: f64, a: f64, q: f64, b: f64) -> f64 { p/a - q/b }"),
        )
    return 1


class TestGetGeneratedCode:
    """Tests for GET /generated-code endpoint."""

    def test_get_generated_code_with_seeded_data(self, e2e_orchestrator):
        """GET /generated-code?paper_id=X returns code entries."""
        port = e2e_orchestrator["port"]
        paper_id = _seed_generated_code(e2e_orchestrator["db_path"])

        resp = urllib.request.urlopen(
            f"http://localhost:{port}/generated-code?paper_id={paper_id}",
            timeout=5,
        )
        data = json.loads(resp.read())

        assert isinstance(data, list)
        assert len(data) == 2
        languages = {row["language"] for row in data}
        assert languages == {"python", "rust"}

    def test_get_generated_code_language_filter(self, e2e_orchestrator):
        """GET /generated-code?paper_id=X&language=python filters correctly."""
        port = e2e_orchestrator["port"]
        paper_id = _seed_generated_code(e2e_orchestrator["db_path"])

        resp = urllib.request.urlopen(
            f"http://localhost:{port}/generated-code?paper_id={paper_id}&language=python",
            timeout=5,
        )
        data = json.loads(resp.read())

        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["language"] == "python"
        assert "kelly" in data[0]["code"]

    def test_get_generated_code_missing_paper_id(self, e2e_orchestrator):
        """GET /generated-code without paper_id returns HTTP 400."""
        port = e2e_orchestrator["port"]

        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(
                f"http://localhost:{port}/generated-code", timeout=5
            )
        assert exc_info.value.code == 400
        body = json.loads(exc_info.value.read())
        assert body["code"] == "VALIDATION_ERROR"

    def test_get_generated_code_nonexistent_paper(self, e2e_orchestrator):
        """GET /generated-code?paper_id=99999 returns empty list."""
        port = e2e_orchestrator["port"]

        resp = urllib.request.urlopen(
            f"http://localhost:{port}/generated-code?paper_id=99999",
            timeout=5,
        )
        data = json.loads(resp.read())

        assert isinstance(data, list)
        assert len(data) == 0


# ---------------------------------------------------------------------------
# GET /runs tests
# ---------------------------------------------------------------------------


class TestGetRuns:
    """Tests for GET /runs endpoint."""

    def test_get_runs_list_empty(self, e2e_orchestrator):
        """GET /runs returns empty list before any runs."""
        port = e2e_orchestrator["port"]

        resp = urllib.request.urlopen(
            f"http://localhost:{port}/runs", timeout=5
        )
        data = json.loads(resp.read())

        assert isinstance(data, list)
        assert len(data) == 0

    def test_get_runs_after_async_run(self, e2e_orchestrator):
        """POST /run then GET /runs shows the run entry."""
        port = e2e_orchestrator["port"]

        # Trigger a run
        body = json.dumps({"paper_id": 1, "stages": 1}).encode()
        req = urllib.request.Request(
            f"http://localhost:{port}/run",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=10)
        run_id = json.loads(resp.read())["run_id"]

        # Wait for completion
        _poll_run(port, run_id)

        # List runs
        resp = urllib.request.urlopen(
            f"http://localhost:{port}/runs", timeout=5
        )
        data = json.loads(resp.read())

        assert isinstance(data, list)
        assert len(data) >= 1
        run_ids = [r["run_id"] for r in data]
        assert run_id in run_ids

    def test_get_runs_nonexistent_id(self, e2e_orchestrator):
        """GET /runs?id=run-nonexistent returns HTTP 404."""
        port = e2e_orchestrator["port"]

        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(
                f"http://localhost:{port}/runs?id=run-nonexistent",
                timeout=5,
            )
        assert exc_info.value.code == 404
