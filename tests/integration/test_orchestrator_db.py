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

from shared.db import transaction
from shared.server import BaseService
from services.orchestrator.main import OrchestratorHandler
from services.orchestrator.pipeline import PipelineRunner


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

        # 5 service calls + 3 external dep calls = 8 total
        mock_get.side_effect = [
            ok_resp, ok_resp, err_resp, ok_resp, ok_resp,  # services
            ok_resp, ok_resp, ok_resp,                      # external: cas, rag, ollama
        ]

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
    def test_run_endpoint_returns_202(self, mock_post):
        """POST /run now returns 202 Accepted with run_id."""
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
        assert resp.status == 202
        data = json.loads(resp.read())

        assert data["status"] == "running"
        assert data["run_id"].startswith("run-")

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

    def _post(self, path, data):
        url = f"http://localhost:{self.port}{path}"
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.getcode(), json.loads(resp.read())
        except urllib.error.HTTPError as e:
            try:
                content = json.loads(e.read())
            except Exception:
                content = {}
            return e.code, content

    def test_requeue_rejects_running(self):
        with transaction(self.db_path) as conn:
            conn.execute(
                "INSERT INTO pipeline_runs (run_id, status, params, stages_requested) "
                "VALUES (?, 'running', ?, 5)",
                ("run-active", '{"query":"test"}'),
            )

        code, data = self._post("/runs/requeue", {"run_id": "run-active"})
        assert code == 409
        assert data["code"] == "RUN_STILL_RUNNING"

    def test_requeue_rejects_completed(self):
        with transaction(self.db_path) as conn:
            conn.execute(
                "INSERT INTO pipeline_runs (run_id, status, params, stages_requested) "
                "VALUES (?, 'completed', ?, 5)",
                ("run-done", '{"query":"test"}'),
            )

        code, data = self._post("/runs/requeue", {"run_id": "run-done"})
        assert code == 409
        assert data["code"] == "RUN_ALREADY_COMPLETED"

    def test_requeue_dry_run_mixed(self):
        with transaction(self.db_path) as conn:
            conn.execute(
                "INSERT INTO pipeline_runs (run_id, status, params, stages_requested) "
                "VALUES (?, 'failed', ?, 5)",
                ("run-f", '{"query":"f"}'),
            )
            conn.execute(
                "INSERT INTO pipeline_runs (run_id, status, params, stages_requested) "
                "VALUES (?, 'completed', ?, 5)",
                ("run-c", '{"query":"c"}'),
            )

        code, data = self._post("/runs/requeue", {
            "run_ids": ["run-f", "run-c"],
            "dry_run": True,
            "skip_preflight": True
        })
        assert code == 200
        assert data["status"] == "dry_run"
        assert data["accepted"] == 1
        assert data["rejected"] == 1
        assert "queued" in data
        assert len(data["queued"]) == 1
        assert data["queued"][0]["source_run_id"] == "run-f"

    @patch("services.orchestrator.main.OrchestratorHandler._check_required_deps")
    def test_requeue_preflight_failure(self, mock_check):
        mock_check.return_value = (False, ["cas"])

        with transaction(self.db_path) as conn:
            conn.execute(
                "INSERT INTO pipeline_runs (run_id, status, params, stages_requested) "
                "VALUES (?, 'failed', ?, 5)",
                ("run-fail", '{"query":"fail"}'),
            )

        code, data = self._post("/runs/requeue", {"run_id": "run-fail"})
        assert code == 503
        assert data["code"] == "PREFLIGHT_FAILED"
        assert "cas" in data["error"]

    @patch("services.orchestrator.pipeline.requests.post")
    def test_requeue_persistence_and_audit(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"ok": True})

        with transaction(self.db_path) as conn:
            conn.execute(
                "INSERT INTO pipeline_runs (run_id, status, params, stages_requested) "
                "VALUES (?, 'failed', ?, 5)",
                ("run-orig", '{"query":"quant","max_papers":5}'),
            )

        code, data = self._post("/runs/requeue", {
            "run_id": "run-orig",
            "skip_preflight": True
        })
        assert code == 202
        new_run_id = data["queued"][0]["run_id"]

        # Give the thread a moment to insert the record
        status = None
        for _ in range(10):
            runner = PipelineRunner(self.db_path)
            status = runner.get_run_status(new_run_id)
            if status:
                break
            time.sleep(0.1)

        assert status is not None
        assert status["status"] in {"running", "failed", "partial", "completed"}
        params = status["params"]
        assert params["query"] == "quant"
        assert params["requeue_of"] == "run-orig"
        assert params["requeue_strategy"] == "rerun_query"
        assert params["requeue_source_status"] == "failed"
        assert "requeue_requested_at" in params

    def test_requeue_rejects_terminal_paper(self):
        with transaction(self.db_path) as conn:
            conn.execute(
                "INSERT INTO papers (id, arxiv_id, title, stage) VALUES (?, ?, ?, ?)",
                (99, "2401.00099", "Terminal Paper", "codegen"),
            )
            conn.execute(
                "INSERT INTO pipeline_runs (run_id, status, params, stages_requested) "
                "VALUES (?, 'failed', ?, 5)",
                ("run-term", '{"query":null,"paper_id":99}'),
            )

        code, data = self._post("/runs/requeue", {"run_id": "run-term"})
        assert code == 409
        assert data["code"] == "RUN_ALREADY_AT_TERMINAL_STAGE"


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

    # -- GET /generated-code tests --

    def test_generated_code_by_paper(self):
        resp = urllib.request.urlopen(
            f"http://localhost:{self.port}/generated-code?paper_id=1"
        )
        data = json.loads(resp.read())
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["language"] == "python"
        assert data[0]["latex"] == "x^2"

    def test_generated_code_filter_language(self):
        resp = urllib.request.urlopen(
            f"http://localhost:{self.port}/generated-code?paper_id=1&language=rust"
        )
        data = json.loads(resp.read())
        assert data == []

    def test_generated_code_filter_formula_id(self):
        resp = urllib.request.urlopen(
            f"http://localhost:{self.port}/generated-code?paper_id=1&formula_id=1"
        )
        data = json.loads(resp.read())
        assert len(data) == 1

    def test_generated_code_requires_paper_id(self):
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(
                f"http://localhost:{self.port}/generated-code"
            )
        assert exc_info.value.code == 400

    def test_generated_code_pagination(self):
        resp = urllib.request.urlopen(
            f"http://localhost:{self.port}/generated-code?paper_id=1&limit=1&offset=0"
        )
        data = json.loads(resp.read())
        assert len(data) == 1

        resp2 = urllib.request.urlopen(
            f"http://localhost:{self.port}/generated-code?paper_id=1&limit=1&offset=1"
        )
        data2 = json.loads(resp2.read())
        assert data2 == []

    def test_generated_code_empty_paper(self):
        resp = urllib.request.urlopen(
            f"http://localhost:{self.port}/generated-code?paper_id=2"
        )
        data = json.loads(resp.read())
        assert data == []


# ---------------------------------------------------------------------------
# POST /search with context_only
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSearchContextOnly:
    """Test POST /search endpoint with context_only parameter."""

    @pytest.fixture(autouse=True)
    def setup(self, initialized_db):
        self.db_path = str(initialized_db)
        self.port = _get_free_port()
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

    @patch("services.orchestrator.main._query_rag")
    def test_search_default_no_context_only(self, mock_rag):
        mock_rag.return_value = {"success": True, "answer": "synthesized response"}
        body = json.dumps({"query": "Kelly criterion"}).encode()
        req = urllib.request.Request(
            f"http://localhost:{self.port}/search",
            data=body, headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req)
        data = json.loads(resp.read())
        assert data["success"] is True
        assert "answer" in data
        assert "context" not in data
        assert data.get("context_only") is False
        mock_rag.assert_called_once_with("Kelly criterion", "hybrid", context_only=False)

    @patch("services.orchestrator.main._query_rag")
    def test_search_context_only_true(self, mock_rag):
        mock_rag.return_value = {"success": True, "context": "raw chunk data here"}
        body = json.dumps({"query": "volatility model", "context_only": True}).encode()
        req = urllib.request.Request(
            f"http://localhost:{self.port}/search",
            data=body, headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req)
        data = json.loads(resp.read())
        assert data["success"] is True
        assert data["context_only"] is True
        assert "context" in data
        assert "answer" not in data
        assert data["context"] == "raw chunk data here"
        mock_rag.assert_called_once_with("volatility model", "hybrid", context_only=True)

    @patch("services.orchestrator.main._query_rag")
    def test_search_context_only_with_mode(self, mock_rag):
        mock_rag.return_value = {"success": True, "context": "local chunks"}
        body = json.dumps({"query": "test", "mode": "local", "context_only": True}).encode()
        req = urllib.request.Request(
            f"http://localhost:{self.port}/search",
            data=body, headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req)
        data = json.loads(resp.read())
        assert data["mode"] == "local"
        assert data["context_only"] is True
        mock_rag.assert_called_once_with("test", "local", context_only=True)

    @patch("services.orchestrator.main._query_rag")
    def test_search_has_time_ms(self, mock_rag):
        mock_rag.return_value = {"success": True, "context": "chunks"}
        body = json.dumps({"query": "test", "context_only": True}).encode()
        req = urllib.request.Request(
            f"http://localhost:{self.port}/search",
            data=body, headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req)
        data = json.loads(resp.read())
        assert "time_ms" in data
        assert isinstance(data["time_ms"], int)


# ---------------------------------------------------------------------------
# GET /runs and async POST /run tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRunsEndpoint:
    """Test GET /runs, async POST /run, and run persistence."""

    @pytest.fixture(autouse=True)
    def setup(self, initialized_db):
        self.db_path = str(initialized_db)
        self.port = _get_free_port()

        with transaction(self.db_path) as conn:
            conn.execute(
                "INSERT INTO papers (arxiv_id, title, stage) VALUES (?, ?, ?)",
                ("2401.00001", "Test Paper", "discovered"),
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

    def test_list_runs_empty(self):
        resp = urllib.request.urlopen(f"http://localhost:{self.port}/runs")
        data = json.loads(resp.read())
        assert isinstance(data, list)
        assert data == []

    def test_run_not_found(self):
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(
                f"http://localhost:{self.port}/runs?id=nonexistent"
            )
        assert exc_info.value.code == 404

    @patch("services.orchestrator.pipeline.requests.post")
    def test_async_run_returns_202(self, mock_post):
        """POST /run returns 202 with run_id immediately."""
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
        assert resp.status == 202

        data = json.loads(resp.read())
        assert "run_id" in data
        assert data["status"] == "running"

    @patch("services.orchestrator.pipeline.requests.post")
    def test_async_run_persists_and_completes(self, mock_post):
        """POST /run → poll GET /runs → status transitions to completed."""
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
        run_id = json.loads(resp.read())["run_id"]

        # Poll until completed (max 10s)
        deadline = time.monotonic() + 10
        final_status = None
        while time.monotonic() < deadline:
            time.sleep(0.5)
            poll_resp = urllib.request.urlopen(
                f"http://localhost:{self.port}/runs?id={run_id}"
            )
            poll_data = json.loads(poll_resp.read())
            if poll_data.get("status") != "running":
                final_status = poll_data
                break

        assert final_status is not None, "Run did not complete within 10s"
        assert final_status["status"] == "completed"
        assert final_status["run_id"] == run_id
        assert final_status["completed_at"] is not None

    def test_list_runs_with_limit(self):
        """list_runs respects limit parameter."""
        runner = OrchestratorHandler.runner
        # Create 3 records directly
        for i in range(3):
            runner._create_run_record(f"run-test-{i}", {}, 1)
            runner._update_run_record(
                f"run-test-{i}",
                {"status": "completed", "stages_completed": 1},
            )

        resp = urllib.request.urlopen(
            f"http://localhost:{self.port}/runs?limit=2"
        )
        data = json.loads(resp.read())
        assert len(data) == 2


# ---------------------------------------------------------------------------
# Run persistence unit tests (no HTTP)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRunPersistence:
    """Test pipeline_runs CRUD operations."""

    def test_create_and_get(self, initialized_db):
        runner = PipelineRunner(str(initialized_db))
        runner._create_run_record("run-001", {"query": "test"}, 3)

        status = runner.get_run_status("run-001")
        assert status is not None
        assert status["run_id"] == "run-001"
        assert status["status"] == "running"
        assert status["params"]["query"] == "test"
        assert status["stages_requested"] == 3

    def test_update_run(self, initialized_db):
        runner = PipelineRunner(str(initialized_db))
        runner._create_run_record("run-002", {}, 2)
        runner._update_run_record(
            "run-002",
            {
                "status": "completed",
                "results": {"discovery": {"ok": True}},
                "errors": [],
                "stages_completed": 2,
            },
        )

        status = runner.get_run_status("run-002")
        assert status["status"] == "completed"
        assert status["completed_at"] is not None
        assert status["stages_completed"] == 2
        assert status["results"]["discovery"]["ok"] is True

    def test_get_nonexistent(self, initialized_db):
        runner = PipelineRunner(str(initialized_db))
        assert runner.get_run_status("nonexistent") is None

    def test_list_runs(self, initialized_db):
        runner = PipelineRunner(str(initialized_db))
        for i in range(5):
            runner._create_run_record(f"run-{i:03d}", {}, 1)

        runs = runner.list_runs(limit=3)
        assert len(runs) == 3
        # Most recent first
        assert runs[0]["run_id"] == "run-004"

    def test_list_runs_empty(self, initialized_db):
        runner = PipelineRunner(str(initialized_db))
        runs = runner.list_runs()
        assert runs == []
