"""Integration tests: orchestrator with real SQLite and HTTP server."""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch

import pytest

from shared.db import get_connection, transaction
from shared.server import BaseService
from services.orchestrator.main import OrchestratorHandler
from services.orchestrator.pipeline import PipelineRunner, ServiceError


def _get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# PipelineRunner with real DB
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPipelineStatus:
    """Test get_pipeline_status() with real DB data."""

    def test_empty_db(self, initialized_db):
        runner = PipelineRunner(str(initialized_db))
        status = runner.get_pipeline_status()
        assert status["papers_by_stage"] == {}
        assert status["formulas_by_stage"] == {}
        assert status["recent_errors"] == []

    def test_papers_by_stage(self, initialized_db):
        db_path = str(initialized_db)
        with transaction(db_path) as conn:
            conn.execute(
                "INSERT INTO papers (arxiv_id, title, stage) VALUES (?, ?, ?)",
                ("2401.00001", "Paper 1", "discovered"),
            )
            conn.execute(
                "INSERT INTO papers (arxiv_id, title, stage) VALUES (?, ?, ?)",
                ("2401.00002", "Paper 2", "discovered"),
            )
            conn.execute(
                "INSERT INTO papers (arxiv_id, title, stage) VALUES (?, ?, ?)",
                ("2401.00003", "Paper 3", "analyzed"),
            )

        runner = PipelineRunner(db_path)
        status = runner.get_pipeline_status()
        assert status["papers_by_stage"]["discovered"] == 2
        assert status["papers_by_stage"]["analyzed"] == 1

    def test_formulas_by_stage(self, initialized_db):
        db_path = str(initialized_db)
        with transaction(db_path) as conn:
            conn.execute(
                "INSERT INTO papers (arxiv_id, title, stage) VALUES (?, ?, ?)",
                ("2401.00001", "Paper 1", "extracted"),
            )
            conn.execute(
                "INSERT INTO formulas (paper_id, latex, latex_hash, stage) "
                "VALUES (?, ?, ?, ?)",
                (1, "x^2", "hash1", "extracted"),
            )
            conn.execute(
                "INSERT INTO formulas (paper_id, latex, latex_hash, stage) "
                "VALUES (?, ?, ?, ?)",
                (1, "y^2", "hash2", "validated"),
            )

        runner = PipelineRunner(db_path)
        status = runner.get_pipeline_status()
        assert status["formulas_by_stage"]["extracted"] == 1
        assert status["formulas_by_stage"]["validated"] == 1

    def test_recent_errors(self, initialized_db):
        db_path = str(initialized_db)
        with transaction(db_path) as conn:
            conn.execute(
                "INSERT INTO papers (arxiv_id, title, stage, error) "
                "VALUES (?, ?, ?, ?)",
                ("2401.00001", "Paper 1", "failed", "timeout"),
            )

        runner = PipelineRunner(db_path)
        status = runner.get_pipeline_status()
        assert len(status["recent_errors"]) == 1
        assert status["recent_errors"][0]["error"] == "timeout"
        assert status["recent_errors"][0]["stage"] == "failed"


@pytest.mark.integration
class TestGetPaperStage:
    """Test _get_paper_stage() with real DB."""

    def test_existing_paper(self, initialized_db):
        db_path = str(initialized_db)
        with transaction(db_path) as conn:
            conn.execute(
                "INSERT INTO papers (arxiv_id, title, stage) VALUES (?, ?, ?)",
                ("2401.00001", "Paper 1", "analyzed"),
            )

        runner = PipelineRunner(db_path)
        assert runner._get_paper_stage(1) == "analyzed"

    def test_nonexistent_paper(self, initialized_db):
        runner = PipelineRunner(str(initialized_db))
        assert runner._get_paper_stage(999) == "unknown"


@pytest.mark.integration
class TestServicesHealth:
    """Test get_services_health() with mocked HTTP."""

    @patch("services.orchestrator.pipeline.requests.get")
    def test_all_healthy(self, mock_get, initialized_db):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "ok", "uptime_seconds": 100}
        mock_get.return_value = mock_resp

        runner = PipelineRunner(str(initialized_db))
        result = runner.get_services_health()

        assert result["all_healthy"] is True
        assert len(result["services"]) == 5
        assert result["services"]["discovery"]["status"] == "ok"

    @patch("services.orchestrator.pipeline.requests.get")
    def test_one_unhealthy(self, mock_get, initialized_db):
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {"status": "ok"}

        err_resp = MagicMock()
        err_resp.status_code = 500

        # 5 calls: discovery ok, analyzer ok, extractor fail, validator ok, codegen ok
        mock_get.side_effect = [ok_resp, ok_resp, err_resp, ok_resp, ok_resp]

        runner = PipelineRunner(str(initialized_db))
        result = runner.get_services_health()

        assert result["all_healthy"] is False
        assert result["services"]["extractor"]["status"] == "error"
        assert result["services"]["discovery"]["status"] == "ok"


# ---------------------------------------------------------------------------
# PipelineRunner.run() with mocked HTTP calls
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRunWithDB:
    """Test full pipeline run with real DB + mocked service calls."""

    @patch("services.orchestrator.pipeline.requests.post")
    def test_batch_run_with_data(self, mock_post, discovered_paper_db):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"processed": 1}
        mock_post.return_value = mock_resp

        runner = PipelineRunner(str(discovered_paper_db))
        result = runner.run(stages=5, max_papers=10, max_formulas=50)

        assert result["status"] == "completed"
        assert result["run_id"].startswith("run-")


# ---------------------------------------------------------------------------
# HTTP endpoint integration tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestOrchestratorHTTP:
    """Test orchestrator HTTP endpoints with real server."""

    @pytest.fixture(autouse=True)
    def setup(self, initialized_db):
        self.db_path = str(initialized_db)
        self.port = _get_free_port()

        # Seed some data
        with transaction(self.db_path) as conn:
            conn.execute(
                "INSERT INTO papers (arxiv_id, title, stage) VALUES (?, ?, ?)",
                ("2401.00001", "Test Paper", "discovered"),
            )

        # Set up handler with runner
        runner = PipelineRunner(self.db_path)
        OrchestratorHandler.runner = runner

        self.service = BaseService(
            "orchestrator", self.port, OrchestratorHandler, self.db_path
        )
        self.thread = threading.Thread(target=self.service.run, daemon=True)
        self.thread.start()
        time.sleep(0.3)
        yield
        if self.service.server:
            self.service.server.shutdown()
        OrchestratorHandler.runner = None
        OrchestratorHandler._routes = None

    def test_health(self):
        resp = urllib.request.urlopen(f"http://localhost:{self.port}/health")
        data = json.loads(resp.read())
        assert data["status"] == "ok"
        assert data["service"] == "orchestrator"

    def test_status(self):
        resp = urllib.request.urlopen(f"http://localhost:{self.port}/status")
        data = json.loads(resp.read())
        assert "papers_by_stage" in data
        assert data["papers_by_stage"]["discovered"] == 1
        assert "cron" in data

    def test_status_services(self):
        resp = urllib.request.urlopen(
            f"http://localhost:{self.port}/status/services"
        )
        data = json.loads(resp.read())
        assert "all_healthy" in data
        assert "services" in data
        assert len(data["services"]) == 5

    @patch("services.orchestrator.pipeline.requests.post")
    def test_run_endpoint(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}
        mock_post.return_value = mock_resp

        body = json.dumps({"query": "test", "stages": 1}).encode()
        req = urllib.request.Request(
            f"http://localhost:{self.port}/run",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req)
        data = json.loads(resp.read())

        assert data["status"] == "completed"
        assert data["run_id"].startswith("run-")
        assert "discovery" in data["results"]

    def test_run_invalid_stages(self):
        body = json.dumps({"stages": 0}).encode()
        req = urllib.request.Request(
            f"http://localhost:{self.port}/run",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req)
        assert exc_info.value.code == 400

    def test_run_invalid_paper_id(self):
        body = json.dumps({"paper_id": "not_int"}).encode()
        req = urllib.request.Request(
            f"http://localhost:{self.port}/run",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req)
        assert exc_info.value.code == 400


# ---------------------------------------------------------------------------
# GET /papers and /formulas endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestQueryEndpoints:
    """Test GET /papers and GET /formulas endpoints."""

    @pytest.fixture(autouse=True)
    def setup(self, initialized_db):
        self.db_path = str(initialized_db)
        self.port = _get_free_port()

        # Seed test data: 2 papers, 2 formulas, 1 validation, 1 codegen
        with transaction(self.db_path) as conn:
            conn.execute(
                "INSERT INTO papers (arxiv_id, title, stage, score) "
                "VALUES (?, ?, ?, ?)",
                ("2401.00001", "Paper One", "analyzed", 0.85),
            )
            conn.execute(
                "INSERT INTO papers (arxiv_id, title, stage) "
                "VALUES (?, ?, ?)",
                ("2401.00002", "Paper Two", "discovered"),
            )
            conn.execute(
                "INSERT INTO formulas (paper_id, latex, latex_hash, stage) "
                "VALUES (?, ?, ?, ?)",
                (1, "x^2", "hash_a", "validated"),
            )
            conn.execute(
                "INSERT INTO formulas (paper_id, latex, latex_hash, stage) "
                "VALUES (?, ?, ?, ?)",
                (1, "y^3", "hash_b", "extracted"),
            )
            conn.execute(
                "INSERT INTO validations (formula_id, engine, is_valid, time_ms) "
                "VALUES (?, ?, ?, ?)",
                (1, "sympy", 1, 120),
            )
            conn.execute(
                "INSERT INTO generated_code (formula_id, language, code, stage) "
                "VALUES (?, ?, ?, ?)",
                (1, "python", "def f(x): return x**2", "codegen"),
            )

        runner = PipelineRunner(self.db_path)
        OrchestratorHandler.runner = runner

        self.service = BaseService(
            "orchestrator", self.port, OrchestratorHandler, self.db_path
        )
        self.thread = threading.Thread(target=self.service.run, daemon=True)
        self.thread.start()
        time.sleep(0.3)
        yield
        if self.service.server:
            self.service.server.shutdown()
        OrchestratorHandler.runner = None
        OrchestratorHandler._routes = None

    def test_list_all_papers(self):
        resp = urllib.request.urlopen(f"http://localhost:{self.port}/papers")
        data = json.loads(resp.read())
        assert isinstance(data, list)
        assert len(data) == 2

    def test_list_papers_filter_stage(self):
        resp = urllib.request.urlopen(
            f"http://localhost:{self.port}/papers?stage=analyzed"
        )
        data = json.loads(resp.read())
        assert len(data) == 1
        assert data[0]["arxiv_id"] == "2401.00001"
        assert data[0]["stage"] == "analyzed"

    def test_list_papers_limit(self):
        resp = urllib.request.urlopen(
            f"http://localhost:{self.port}/papers?limit=1"
        )
        data = json.loads(resp.read())
        assert len(data) == 1

    def test_paper_detail_by_id(self):
        resp = urllib.request.urlopen(
            f"http://localhost:{self.port}/papers?id=1"
        )
        data = json.loads(resp.read())
        assert isinstance(data, dict)
        assert data["arxiv_id"] == "2401.00001"
        assert "formulas" in data
        assert len(data["formulas"]) == 2
        # Check nested validations and generated_code
        validated_formula = next(
            f for f in data["formulas"] if f["latex"] == "x^2"
        )
        assert len(validated_formula["validations"]) == 1
        assert validated_formula["validations"][0]["engine"] == "sympy"
        assert len(validated_formula["generated_code"]) == 1
        assert validated_formula["generated_code"][0]["language"] == "python"

    def test_paper_detail_not_found(self):
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(
                f"http://localhost:{self.port}/papers?id=999"
            )
        assert exc_info.value.code == 404

    def test_list_formulas_all(self):
        resp = urllib.request.urlopen(
            f"http://localhost:{self.port}/formulas"
        )
        data = json.loads(resp.read())
        assert isinstance(data, list)
        assert len(data) == 2

    def test_list_formulas_by_paper(self):
        resp = urllib.request.urlopen(
            f"http://localhost:{self.port}/formulas?paper_id=1"
        )
        data = json.loads(resp.read())
        assert len(data) == 2
        assert all(f["paper_id"] == 1 for f in data)

    def test_list_formulas_by_stage(self):
        resp = urllib.request.urlopen(
            f"http://localhost:{self.port}/formulas?stage=validated"
        )
        data = json.loads(resp.read())
        assert len(data) == 1
        assert data[0]["latex"] == "x^2"

    def test_list_formulas_combined_filter(self):
        resp = urllib.request.urlopen(
            f"http://localhost:{self.port}/formulas?paper_id=1&stage=extracted"
        )
        data = json.loads(resp.read())
        assert len(data) == 1
        assert data[0]["latex"] == "y^3"

    def test_list_formulas_empty_result(self):
        resp = urllib.request.urlopen(
            f"http://localhost:{self.port}/formulas?paper_id=999"
        )
        data = json.loads(resp.read())
        assert data == []
