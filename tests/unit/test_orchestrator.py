"""Unit tests for orchestrator service — pipeline dispatch, retry, scheduler."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest
import requests

from shared.config import get_default_max_formulas
from shared.db import transaction
from services.orchestrator.main import (
    OrchestratorHandler,
    _cron_run,
    _query_rag,
    _run_pipeline_async,
)
from services.orchestrator.pipeline import (
    RequeueError,
    STAGE_ORDER,
    STAGE_PARAMS,
    PipelineRunner,
    ServiceError,
    _stage_port,
    _stage_url,
)
from services.orchestrator.scheduler import create_scheduler


def _assert_stage_skipped(result: dict, stage_name: str, upstream_stage: str) -> None:
    """Assert a stage result was explicitly marked as skipped."""
    stage_result = result["results"][stage_name]
    assert (
        stage_result.get("status") == "skipped"
        or stage_result.get("skipped") is True
    )
    reason = stage_result.get("reason", stage_result.get("error", ""))
    assert upstream_stage in reason


# ---------------------------------------------------------------------------
# PipelineRunner._resolve_stages
# ---------------------------------------------------------------------------


class TestResolveStages:
    """Tests for stage resolution logic."""

    def setup_method(self):
        self.runner = PipelineRunner.__new__(PipelineRunner)
        self.runner.db_path = ":memory:"

    def test_query_starts_from_discovery(self):
        stages = self.runner._resolve_stages(query="test", paper_id=None, stages=5)
        assert len(stages) == 5
        assert stages[0][0] == "discovery"
        assert stages[-1][0] == "codegen"

    def test_query_limits_stages(self):
        stages = self.runner._resolve_stages(query="test", paper_id=None, stages=2)
        assert len(stages) == 2
        assert stages[0][0] == "discovery"
        assert stages[1][0] == "analyzer"

    def test_batch_mode_all_stages(self):
        stages = self.runner._resolve_stages(query=None, paper_id=None, stages=5)
        assert len(stages) == 5

    def test_batch_mode_limited(self):
        stages = self.runner._resolve_stages(query=None, paper_id=None, stages=3)
        assert len(stages) == 3

    @patch.object(PipelineRunner, "_get_paper_stage", return_value="discovered")
    def test_paper_id_starts_after_current_stage(self, mock_stage):
        stages = self.runner._resolve_stages(query=None, paper_id=42, stages=3)
        assert stages[0][0] == "analyzer"
        assert len(stages) == 3

    @patch.object(PipelineRunner, "_get_paper_stage", return_value="analyzed")
    def test_paper_id_from_analyzed(self, mock_stage):
        stages = self.runner._resolve_stages(query=None, paper_id=42, stages=2)
        assert stages[0][0] == "extractor"
        assert len(stages) == 2

    @patch.object(PipelineRunner, "_get_paper_stage", return_value="extracted")
    def test_paper_id_from_extracted(self, mock_stage):
        """Paper currently extracted → starts from validator."""
        stages = self.runner._resolve_stages(query=None, paper_id=42, stages=2)
        assert stages[0][0] == "validator"
        assert len(stages) == 2

    @patch.object(PipelineRunner, "_get_paper_stage", return_value="validated")
    def test_paper_id_from_validated(self, mock_stage):
        stages = self.runner._resolve_stages(query=None, paper_id=42, stages=5)
        assert stages[0][0] == "codegen"
        assert len(stages) == 1  # Only codegen left

    @patch.object(PipelineRunner, "_get_paper_stage", return_value="rejected")
    def test_rejected_paper_returns_empty(self, mock_stage):
        stages = self.runner._resolve_stages(query=None, paper_id=42, stages=5)
        assert stages == []

    @patch.object(PipelineRunner, "_get_paper_stage", return_value="failed")
    def test_failed_paper_returns_empty(self, mock_stage):
        stages = self.runner._resolve_stages(query=None, paper_id=42, stages=5)
        assert stages == []

    def test_stages_clamped_to_1_min(self):
        stages = self.runner._resolve_stages(query="test", paper_id=None, stages=0)
        assert len(stages) == 1

    def test_stages_clamped_to_5_max(self):
        stages = self.runner._resolve_stages(query="test", paper_id=None, stages=99)
        assert len(stages) == 5

    def test_stages_clamped_exactly_at_5(self):
        """stages=6 should still return exactly 5 (not 6)."""
        stages = self.runner._resolve_stages(query="test", paper_id=None, stages=6)
        assert len(stages) == 5

    @patch.object(PipelineRunner, "_get_paper_stage", return_value="unknown")
    def test_unknown_stage_starts_from_discovery(self, mock_stage):
        """Unknown stage defaults to idx=-1+1=0, i.e. discovery."""
        stages = self.runner._resolve_stages(query=None, paper_id=42, stages=5)
        assert stages[0][0] == "discovery"
        assert len(stages) == 5

    @patch.object(PipelineRunner, "_get_paper_stage", return_value="codegen")
    def test_codegen_stage_returns_empty(self, mock_stage):
        """Paper at codegen stage has nothing left to do."""
        stages = self.runner._resolve_stages(query=None, paper_id=42, stages=5)
        assert stages == []


# ---------------------------------------------------------------------------
# PipelineRunner._build_stage_params
# ---------------------------------------------------------------------------


class TestBuildStageParams:
    """Tests for parameter mapping to services."""

    def setup_method(self):
        self.runner = PipelineRunner.__new__(PipelineRunner)
        self.params = {
            "query": "kelly criterion",
            "topic": "market microstructure",
            "paper_id": 42,
            "max_papers": 10,
            "max_formulas": 50,
            "force": True,
        }

    def test_discovery_params(self):
        result = self.runner._build_stage_params("discovery", self.params)
        assert result == {"query": "kelly criterion", "max_results": 10}

    def test_analyzer_params(self):
        result = self.runner._build_stage_params("analyzer", self.params)
        assert result == {
            "paper_id": 42,
            "topic": "market microstructure",
            "max_papers": 10,
            "force": True,
        }

    def test_extractor_params(self):
        result = self.runner._build_stage_params("extractor", self.params)
        assert result == {"paper_id": 42, "max_papers": 10, "force": True}

    def test_validator_params(self):
        result = self.runner._build_stage_params("validator", self.params)
        assert result == {"paper_id": 42, "max_formulas": 50, "force": True}

    def test_codegen_params(self):
        result = self.runner._build_stage_params("codegen", self.params)
        assert result == {"paper_id": 42, "max_formulas": 50, "force": True}

    def test_none_values_excluded(self):
        params = {"query": None, "paper_id": None, "max_papers": 10,
                  "max_formulas": None, "force": False}
        result = self.runner._build_stage_params("discovery", params)
        assert result == {"max_results": 10}

    def test_unknown_service_returns_empty(self):
        result = self.runner._build_stage_params("unknown", self.params)
        assert result == {}

    def test_batch_mode_discovery_no_query(self):
        params = {"query": None, "paper_id": None, "max_papers": 10,
                  "max_formulas": 50, "force": False}
        result = self.runner._build_stage_params("discovery", params)
        assert result == {"max_results": 10}


# ---------------------------------------------------------------------------
# PipelineRunner._generate_run_id
# ---------------------------------------------------------------------------


class TestGenerateRunId:
    """Tests for run ID generation."""

    def test_format(self):
        run_id = PipelineRunner._generate_run_id()
        assert run_id.startswith("run-")
        parts = run_id.split("-")
        assert len(parts) == 4  # run, date, time, hex

    def test_uniqueness(self):
        ids = {PipelineRunner._generate_run_id() for _ in range(100)}
        assert len(ids) == 100

    def test_length(self):
        run_id = PipelineRunner._generate_run_id()
        assert len(run_id) == 26  # run-YYYYMMDD-HHMMSS-XXXXXX


# ---------------------------------------------------------------------------
# PipelineRunner._call_service_with_retry
# ---------------------------------------------------------------------------


class TestCallServiceWithRetry:
    """Tests for HTTP call retry logic."""

    def setup_method(self):
        self.runner = PipelineRunner.__new__(PipelineRunner)
        self.runner.timeout = 5
        self.runner.retry_max = 2
        self.runner.retry_backoff = 1.0  # Fast for tests

    @patch("services.orchestrator.pipeline.requests.post")
    def test_success_first_try(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"papers_found": 5}
        mock_post.return_value = mock_resp

        result = self.runner._call_service_with_retry(
            "http://localhost:8770/process", {"query": "test"}
        )
        assert result == {"papers_found": 5}
        assert mock_post.call_count == 1

    @patch("services.orchestrator.pipeline.requests.post")
    def test_4xx_no_retry(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {"error": "Bad request"}
        mock_resp.text = '{"error": "Bad request"}'
        mock_post.return_value = mock_resp

        with pytest.raises(ServiceError, match="HTTP 400"):
            self.runner._call_service_with_retry(
                "http://localhost:8770/process", {}
            )
        assert mock_post.call_count == 1  # No retry on 4xx

    @patch("services.orchestrator.pipeline.time.sleep")
    @patch("services.orchestrator.pipeline.requests.post")
    def test_5xx_retries_then_succeeds(self, mock_post, mock_sleep):
        fail_resp = MagicMock()
        fail_resp.status_code = 503
        fail_resp.text = "Service Unavailable"

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {"success": True}

        mock_post.side_effect = [fail_resp, ok_resp]

        result = self.runner._call_service_with_retry(
            "http://localhost:8770/process", {}
        )
        assert result == {"success": True}
        assert mock_post.call_count == 2
        mock_sleep.assert_called_once()

    @patch("services.orchestrator.pipeline.time.sleep")
    @patch("services.orchestrator.pipeline.requests.post")
    def test_max_retries_exhausted(self, mock_post, mock_sleep):
        fail_resp = MagicMock()
        fail_resp.status_code = 503
        fail_resp.text = "Service Unavailable"
        mock_post.return_value = fail_resp

        with pytest.raises(ServiceError, match="HTTP 503"):
            self.runner._call_service_with_retry(
                "http://localhost:8770/process", {}
            )
        assert mock_post.call_count == 3  # 1 + 2 retries

    @patch("services.orchestrator.pipeline.time.sleep")
    @patch("services.orchestrator.pipeline.requests.post")
    def test_connection_error_retries(self, mock_post, mock_sleep):
        mock_post.side_effect = requests.ConnectionError("Connection refused")

        with pytest.raises(ServiceError, match="Connection refused"):
            self.runner._call_service_with_retry(
                "http://localhost:8770/process", {}
            )
        assert mock_post.call_count == 3

    @patch("services.orchestrator.pipeline.time.sleep")
    @patch("services.orchestrator.pipeline.requests.post")
    def test_timeout_retries(self, mock_post, mock_sleep):
        mock_post.side_effect = requests.Timeout("Read timed out")

        with pytest.raises(ServiceError, match="Timeout"):
            self.runner._call_service_with_retry(
                "http://localhost:8770/process", {}
            )
        assert mock_post.call_count == 3


# ---------------------------------------------------------------------------
# PipelineRunner.run (mocked dispatch)
# ---------------------------------------------------------------------------


class TestRunPipeline:
    """Tests for full pipeline run with mocked services."""

    def setup_method(self):
        self.runner = PipelineRunner.__new__(PipelineRunner)
        self.runner.db_path = ":memory:"
        self.runner.timeout = 5
        self.runner.retry_max = 0
        self.runner.retry_backoff = 1.0
        self.runner.STAGE_TIMEOUTS = {"analyzer": 1800, "codegen": 900}

    @patch.object(PipelineRunner, "_call_service_with_retry")
    def test_query_run_all_stages(self, mock_call):
        mock_call.return_value = {"papers_found": 3}

        result = self.runner.run(query="test", stages=5)

        assert result["status"] == "completed"
        assert result["stages_completed"] == 5
        assert result["run_id"].startswith("run-")
        assert "discovery" in result["results"]

    @patch.object(PipelineRunner, "_call_service_with_retry")
    def test_partial_failure(self, mock_call):
        mock_call.side_effect = [
            {"papers_found": 3},
            ServiceError("Analyzer down"),
        ]

        result = self.runner.run(query="test", stages=5)

        assert result["status"] == "partial"
        assert result["stages_completed"] == 1
        assert result["stages_skipped"] == 3
        assert len(result["errors"]) == 1
        assert mock_call.call_count == 2
        _assert_stage_skipped(result, "extractor", "analyzer")
        _assert_stage_skipped(result, "validator", "analyzer")
        _assert_stage_skipped(result, "codegen", "analyzer")

    @patch.object(PipelineRunner, "_call_service_with_retry")
    def test_analyzer_zero_progress_with_errors_is_treated_as_failure(self, mock_call):
        mock_call.side_effect = [
            {"papers_found": 3},
            {
                "papers_analyzed": 0,
                "papers_accepted": 0,
                "papers_rejected": 0,
                "errors": ["paper 99: all LLM providers failed"],
            },
        ]

        result = self.runner.run(query="test", stages=5)

        assert result["status"] == "partial"
        assert result["stages_completed"] == 1
        assert result["results"]["analyzer"]["status"] == "failed"
        assert "Analyzer returned no progress" in result["errors"][0]
        _assert_stage_skipped(result, "extractor", "analyzer")
        _assert_stage_skipped(result, "validator", "analyzer")
        _assert_stage_skipped(result, "codegen", "analyzer")

    @patch.object(PipelineRunner, "_call_service_with_retry")
    def test_all_stages_fail(self, mock_call):
        mock_call.side_effect = ServiceError("all down")

        result = self.runner.run(query="test", stages=5)

        assert result["status"] == "failed"
        assert result["stages_completed"] == 0
        assert result["stages_skipped"] == 4
        assert len(result["errors"]) == 1
        assert mock_call.call_count == 1
        _assert_stage_skipped(result, "analyzer", "discovery")
        _assert_stage_skipped(result, "extractor", "discovery")
        _assert_stage_skipped(result, "validator", "discovery")
        _assert_stage_skipped(result, "codegen", "discovery")

    @patch.object(PipelineRunner, "_get_paper_stage", return_value="discovered")
    @patch.object(PipelineRunner, "_call_service_with_retry")
    def test_paper_scoped_failure_skips_downstream(self, mock_call, mock_stage):
        mock_call.side_effect = [ServiceError("Analyzer down")]

        result = self.runner.run(paper_id=42, stages=4)

        assert result["status"] == "failed"
        assert result["stages_completed"] == 0
        assert result["stages_skipped"] == 3
        assert mock_call.call_count == 1
        _assert_stage_skipped(result, "extractor", "analyzer")
        _assert_stage_skipped(result, "validator", "analyzer")
        _assert_stage_skipped(result, "codegen", "analyzer")

    @patch.object(PipelineRunner, "_call_service_with_retry")
    def test_run_returns_time_ms(self, mock_call):
        mock_call.return_value = {"ok": True}

        result = self.runner.run(query="test", stages=1)

        assert "time_ms" in result
        assert isinstance(result["time_ms"], int)


# ---------------------------------------------------------------------------
# Stage order and params constants
# ---------------------------------------------------------------------------


class TestConstants:
    """Tests for module-level constants."""

    def test_stage_order_has_5_stages(self):
        assert len(STAGE_ORDER) == 5

    def test_stage_order_names(self):
        names = [s[0] for s in STAGE_ORDER]
        assert names == ["discovery", "analyzer", "extractor", "validator", "codegen"]

    def test_stage_order_ports(self):
        ports = [s[1] for s in STAGE_ORDER]
        expected = [
            int(os.environ.get("RP_DISCOVERY_PORT", "8770")),
            int(os.environ.get("RP_ANALYZER_PORT", "8771")),
            int(os.environ.get("RP_EXTRACTOR_PORT", "8772")),
            int(os.environ.get("RP_VALIDATOR_PORT", "8773")),
            int(os.environ.get("RP_CODEGEN_PORT", "8774")),
        ]
        assert ports == expected

    def test_stage_port_reads_env_override(self):
        with patch.dict(os.environ, {"RP_DISCOVERY_PORT": "9900"}, clear=False):
            assert _stage_port("discovery", 8770) == 9900

    def test_stage_url_reads_env_override(self):
        with patch.dict(os.environ, {"RP_DISCOVERY_URL": "http://discovery:9900"}, clear=False):
            assert _stage_url("discovery", 8770) == "http://discovery:9900"

    def test_stage_params_all_services_covered(self):
        for name, _ in STAGE_ORDER:
            assert name in STAGE_PARAMS


# ---------------------------------------------------------------------------
# ServiceError
# ---------------------------------------------------------------------------


class TestServiceError:
    """Tests for ServiceError exception."""

    def test_is_exception(self):
        assert issubclass(ServiceError, Exception)

    def test_message_preserved(self):
        err = ServiceError("test error")
        assert str(err) == "test error"


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


class TestScheduler:
    """Tests for cron scheduler creation."""

    def test_disabled_by_default(self, clean_env):
        scheduler = create_scheduler(lambda: None)
        assert scheduler is None

    def test_enabled_via_env(self, clean_env):
        os.environ["RP_ORCHESTRATOR_CRON_ENABLED"] = "true"
        scheduler = create_scheduler(lambda: None)
        assert scheduler is not None
        jobs = scheduler.get_jobs()
        assert len(jobs) == 1
        assert jobs[0].id == "pipeline_cron"

    def test_custom_cron_expression(self, clean_env):
        os.environ["RP_ORCHESTRATOR_CRON_ENABLED"] = "true"
        os.environ["RP_ORCHESTRATOR_CRON"] = "*/15 * * * *"
        scheduler = create_scheduler(lambda: None)
        assert scheduler is not None
        jobs = scheduler.get_jobs()
        assert len(jobs) == 1

    def test_disabled_with_explicit_false(self, clean_env):
        os.environ["RP_ORCHESTRATOR_CRON_ENABLED"] = "false"
        scheduler = create_scheduler(lambda: None)
        assert scheduler is None

    def test_disabled_with_zero(self, clean_env):
        os.environ["RP_ORCHESTRATOR_CRON_ENABLED"] = "0"
        scheduler = create_scheduler(lambda: None)
        assert scheduler is None


# ---------------------------------------------------------------------------
# _query_rag
# ---------------------------------------------------------------------------


class TestQueryRag:
    """Tests for RAGAnything query helper."""

    @patch("services.orchestrator.main.urllib.request.urlopen")
    def test_returns_parsed_json(self, mock_urlopen):
        from services.orchestrator.main import _query_rag

        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"success": true, "answer": "Kelly is optimal"}'
        mock_urlopen.return_value = mock_resp

        result = _query_rag("Kelly criterion", "hybrid")

        assert result["success"] is True
        assert "Kelly" in result["answer"]
        mock_urlopen.assert_called_once()

    @patch("services.orchestrator.main.urllib.request.urlopen")
    def test_sends_correct_payload(self, mock_urlopen):
        import json
        from services.orchestrator.main import _query_rag

        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"success": true, "answer": ""}'
        mock_urlopen.return_value = mock_resp

        _query_rag("test query", "local")

        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        body = json.loads(req.data.decode())
        assert body["query"] == "test query"
        assert body["mode"] == "local"

    @patch("services.orchestrator.main.urllib.request.urlopen")
    def test_raises_on_network_error(self, mock_urlopen):
        from services.orchestrator.main import _query_rag

        mock_urlopen.side_effect = ConnectionError("refused")

        with pytest.raises(ConnectionError):
            _query_rag("test", "hybrid")

    @patch("services.orchestrator.main.urllib.request.urlopen")
    def test_context_only_sends_param(self, mock_urlopen):
        import json
        from services.orchestrator.main import _query_rag

        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"success": true, "context": "raw chunks"}'
        mock_urlopen.return_value = mock_resp

        result = _query_rag("test query", "hybrid", context_only=True)

        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        body = json.loads(req.data.decode())
        assert body["context_only"] is True
        assert result["context"] == "raw chunks"

    @patch("services.orchestrator.main.urllib.request.urlopen")
    def test_context_only_false_by_default(self, mock_urlopen):
        import json
        from services.orchestrator.main import _query_rag

        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"success": true, "answer": "synthesized"}'
        mock_urlopen.return_value = mock_resp

        _query_rag("test query", "hybrid")

        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        body = json.loads(req.data.decode())
        assert body["context_only"] is False


# ---------------------------------------------------------------------------
# OrchestratorHandler._search_fallback
# ---------------------------------------------------------------------------


class TestSearchFallback:
    """Tests for SQLite fallback search."""

    def test_matches_by_title(self, tmp_path):
        from shared.db import init_db, transaction
        from services.orchestrator.main import OrchestratorHandler

        db = str(tmp_path / "test.db")
        init_db(db)

        with transaction(db) as conn:
            conn.execute(
                "INSERT INTO papers (arxiv_id, title, abstract, stage) "
                "VALUES (?, ?, ?, ?)",
                ("2401.00001", "Kelly Criterion in Finance", "Optimal betting", "analyzed"),
            )
            conn.execute(
                "INSERT INTO papers (arxiv_id, title, abstract, stage) "
                "VALUES (?, ?, ?, ?)",
                ("2401.00002", "Unrelated Topic", "Nothing relevant", "discovered"),
            )

        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.db_path = db

        result = handler._search_fallback("Kelly")

        assert result["success"] is True
        assert result["mode"] == "fallback"
        assert len(result["papers"]) == 1
        assert "Kelly" in result["papers"][0]["title"]

    def test_no_matches_returns_empty(self, tmp_path):
        from shared.db import init_db
        from services.orchestrator.main import OrchestratorHandler

        db = str(tmp_path / "test.db")
        init_db(db)

        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.db_path = db

        result = handler._search_fallback("nonexistent")

        assert result["success"] is True
        assert result["papers"] == []


# ---------------------------------------------------------------------------
# services/orchestrator/main.py Handler Tests
# ---------------------------------------------------------------------------


class TestOrchestratorHandler:
    """Tests for OrchestratorHandler routes."""

    @patch("threading.Thread")
    @patch("services.orchestrator.pipeline.PipelineRunner._generate_run_id", return_value="run-123")
    def test_handle_run_async(self, mock_gen_id, mock_thread, initialized_db):
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.runner = MagicMock()
        handler.runner.get_pipeline_status.return_value = {"active_runs": 0}
        handler.runner._resolve_stages.return_value = [
            ("discovery", 8770), ("analyzer", 8771), ("extractor", 8772),
        ]
        handler.runner.check_external_health.return_value = {
            "all_healthy": True,
            "deps": {
                "cas": {"url": "http://localhost:8769", "healthy": True},
                "rag": {"url": "http://localhost:8767", "healthy": True},
                "ollama": {"url": "http://localhost:11434", "healthy": True},
            },
        }
        handler.send_json = MagicMock()

        handler.handle_run({"query": "test", "stages": 3})
        
        handler.send_json.assert_called_once_with(
            {"run_id": "run-123", "status": "running"},
            status=202,
        )
        mock_thread.assert_called_once()

    @patch("services.orchestrator.main._start_pipeline_thread")
    @patch(
        "services.orchestrator.pipeline.PipelineRunner._generate_run_id",
        return_value="run-124",
    )
    def test_handle_run_uses_shared_default_max_formulas(
        self, _mock_gen_id, mock_start_thread
    ):
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.runner = MagicMock()
        handler.runner._resolve_stages.return_value = [("discovery", 8770)]
        handler.runner.check_external_health.return_value = {
            "all_healthy": True,
            "deps": {
                "cas": {"healthy": True},
                "rag": {"healthy": True},
                "ollama": {"healthy": True},
            },
        }
        handler.send_json = MagicMock()

        handler.handle_run({"query": "test", "stages": 1})

        assert mock_start_thread.call_args.kwargs["max_formulas"] == (
            get_default_max_formulas()
        )

    def test_handle_github_repos_no_paper_id(self):
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.path = "/github-repos"
        handler.send_error_json = MagicMock()
        res = handler.handle_github_repos()
        assert res is None
        handler.send_error_json.assert_called_once()
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.runner = MagicMock()
        handler.send_error_json = MagicMock()
        
        # stages=99 is invalid (max 5)
        res = handler.handle_run({"stages": 99})
        assert res is None
        handler.send_error_json.assert_called_once()
        args = handler.send_error_json.call_args[0]
        assert args[1] == "VALIDATION_ERROR"

    def test_handle_status(self, initialized_db):
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.runner = MagicMock()
        handler.runner.get_pipeline_status.return_value = {"active_runs": 0}
        
        res = handler.handle_status()
        assert res["active_runs"] == 0
        assert "cron" in res

    def test_handle_papers_list(self, analyzed_paper_db):
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.db_path = str(analyzed_paper_db)
        handler.path = "/papers?stage=analyzed"
        
        res = handler.handle_papers()
        assert isinstance(res, list)
        assert len(res) == 1
        assert res[0]["stage"] == "analyzed"

    def test_handle_papers_detail_not_found(self, initialized_db):
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.db_path = str(initialized_db)
        handler.path = "/papers?id=999"
        handler.send_error_json = MagicMock()
        
        res = handler.handle_papers()
        assert res is None
        handler.send_error_json.assert_called_once()

    def test_handle_generated_code_no_formulas(self, validated_formula_db):
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.db_path = str(validated_formula_db)
        handler.path = "/generated-code?paper_id=1"
        
        res = handler.handle_generated_code()
        assert isinstance(res, list)
        assert len(res) == 0

    def test_handle_formulas(self, validated_formula_db):
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.db_path = str(validated_formula_db)
        handler.path = "/formulas?paper_id=1"
        
        res = handler.handle_formulas()
        assert len(res) == 1
        assert res[0]["paper_id"] == 1

    def test_handle_generated_code(self, validated_formula_db):
        db_path = str(validated_formula_db)
        from shared.db import transaction
        with transaction(db_path) as conn:
            conn.execute(
                "INSERT INTO generated_code (formula_id, language, code) "
                "VALUES (?, ?, ?)",
                (1, "python", "def f(): pass")
            )
        
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.db_path = db_path
        handler.path = "/generated-code?paper_id=1"
        
        res = handler.handle_generated_code()
        assert len(res) == 1
        assert res[0]["language"] == "python"

    def test_handle_generated_code_no_paper_id(self):
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.path = "/generated-code"
        handler.send_error_json = MagicMock()
        
        res = handler.handle_generated_code()
        assert res is None
        handler.send_error_json.assert_called_once()

    def test_db_path_required_fails_when_none(self):
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.db_path = None
        with pytest.raises(AssertionError, match="Database path not configured"):
            handler._db_path_required()

    def test_handle_formulas_no_paper_id(self, initialized_db):
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.db_path = str(initialized_db)
        handler.path = "/formulas"
        handler.send_error_json = MagicMock()
        
        res = handler.handle_formulas()
        # It returns [] (all formulas) when no paper_id given
        assert isinstance(res, list)
        assert len(res) == 0

    @patch("services.orchestrator.main.search_and_analyze")
    def test_handle_search_github(self, mock_sa, initialized_db):
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.db_path = str(initialized_db)
        mock_sa.return_value = {"success": True}
        
        res = handler.handle_search_github({"paper_id": 1})
        assert res["success"] is True

    def test_handle_github_repos(self, initialized_db):
        db_path = str(initialized_db)
        with transaction(db_path) as conn:
            conn.execute("INSERT INTO papers (id, title, stage) VALUES (1, 't', 'analyzed')")
            conn.execute("INSERT INTO github_repos (paper_id, full_name, url, clone_url) VALUES (1, 'u/r', 'h', 'c')")
            
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.db_path = db_path
        handler.path = "/github-repos?paper_id=1"
        
        res = handler.handle_github_repos()
        assert len(res) == 1
        assert res[0]["repo"]["full_name"] == "u/r"

    @patch("services.orchestrator.main._query_rag")
    def test_handle_search_rag(self, mock_rag, initialized_db):
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.db_path = str(initialized_db)
        mock_rag.return_value = {"success": True, "answer": "The answer"}
        
        res = handler.handle_search({"query": "test"})
        assert res["answer"] == "The answer"

    @patch("services.orchestrator.main._query_rag", side_effect=Exception("RAG Down"))
    def test_handle_search_fallback(self, mock_rag, initialized_db):
        db_path = str(initialized_db)
        with transaction(db_path) as conn:
            conn.execute("INSERT INTO papers (id, title, stage) VALUES (1, 'Kelly criterion', 'analyzed')")
            
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.db_path = db_path
        
        res = handler.handle_search({"query": "Kelly"})
        assert res["mode"] == "fallback"
        assert len(res["papers"]) == 1

    def test_handle_services_status(self):
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.runner = MagicMock()
        handler.runner.get_services_health.return_value = {"discovery": "ok"}
        
        res = handler.handle_services_status()
        assert res["discovery"] == "ok"

    def test_handle_runs_list(self):
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.runner = MagicMock()
        handler.runner.list_runs.return_value = [{"run_id": "1"}]
        handler.path = "/runs"
        
        res = handler.handle_runs()
        assert len(res) == 1

    def test_handle_runs_detail(self):
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.runner = MagicMock()
        handler.runner.get_run_status.return_value = {"run_id": "run-1"}
        handler.path = "/runs?id=run-1"
        
        res = handler.handle_runs()
        assert res["run_id"] == "run-1"

    def test_handle_runs_not_found(self):
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.runner = MagicMock()
        handler.runner.get_run_status.return_value = None
        handler.path = "/runs?id=invalid"
        handler.send_error_json = MagicMock()
        
        res = handler.handle_runs()
        assert res is None
        handler.send_error_json.assert_called_with(
            "Run invalid not found", "NOT_FOUND", 404
        )

    @patch("services.orchestrator.main._start_pipeline_thread")
    def test_handle_requeue_runs_single(self, mock_start_thread):
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.runner = MagicMock()
        handler.runner.build_requeue_plan.return_value = {
            "source_run_id": "run-old",
            "new_run_id": "run-new",
            "strategy": "rerun_query",
            "stages": 5,
            "stage_names": [
                "discovery",
                "analyzer",
                "extractor",
                "validator",
                "codegen",
            ],
            "params": {
                "query": "quant finance topic",
                "topic": None,
                "paper_id": None,
                "max_papers": 10,
                "max_formulas": 50,
                "force": False,
                "requeue_of": "run-old",
                "requeue_strategy": "rerun_query",
                "requeue_source_status": "partial",
                "requeue_requested_at": "2026-03-10T12:00:00+00:00",
                "requeue_source_stages_completed": 1,
                "requeue_source_stages_requested": 5,
                "requeue_source_failed_stage": "analyzer",
            },
        }
        handler.runner.check_external_health.return_value = {
            "all_healthy": True,
            "deps": {
                "cas": {"healthy": True},
                "rag": {"healthy": True},
                "ollama": {"healthy": True},
            },
        }
        handler.send_json = MagicMock()

        handler.handle_requeue_runs({"run_id": "run-old"})

        handler.send_json.assert_called_once()
        payload = handler.send_json.call_args.args[0]
        assert payload["status"] == "accepted"
        assert payload["accepted"] == 1
        assert payload["queued"][0]["run_id"] == "run-new"
        mock_start_thread.assert_called_once()
        kwargs = mock_start_thread.call_args.kwargs
        assert kwargs["extra_params"]["requeue_of"] == "run-old"
        assert kwargs["stages"] == 5

    def test_handle_requeue_runs_rejects_all_invalid(self):
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.runner = MagicMock()
        handler.runner.build_requeue_plan.side_effect = RequeueError(
            "Run run-old already completed successfully",
            code="RUN_ALREADY_COMPLETED",
            status=409,
        )
        handler.send_error_json = MagicMock()

        res = handler.handle_requeue_runs({"run_id": "run-old"})

        assert res is None
        handler.send_error_json.assert_called_once()
        assert handler.send_error_json.call_args.args[:3] == (
            "Run run-old already completed successfully",
            "RUN_ALREADY_COMPLETED",
            409,
        )

    @patch("services.orchestrator.main._start_pipeline_thread")
    def test_handle_requeue_runs_bulk_accepts_and_rejects(self, mock_start_thread):
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.runner = MagicMock()
        handler.runner.build_requeue_plan.side_effect = [
            {
                "source_run_id": "run-old-a",
                "new_run_id": "run-new-a",
                "strategy": "resume_from_current_stage",
                "stages": 2,
                "stage_names": ["validator", "codegen"],
                "params": {
                    "query": None,
                    "topic": None,
                    "paper_id": 42,
                    "max_papers": 10,
                    "max_formulas": 50,
                    "force": False,
                    "requeue_of": "run-old-a",
                    "requeue_strategy": "resume_from_current_stage",
                    "requeue_source_status": "partial",
                    "requeue_requested_at": "2026-03-10T12:00:00+00:00",
                    "requeue_source_stages_completed": 2,
                    "requeue_source_stages_requested": 4,
                    "requeue_source_failed_stage": "validator",
                },
            },
            RequeueError(
                "Run run-old-b is still running and cannot be requeued",
                code="RUN_STILL_RUNNING",
                status=409,
            ),
        ]
        handler.runner.check_external_health.return_value = {
            "all_healthy": True,
            "deps": {
                "cas": {"healthy": True},
                "rag": {"healthy": True},
                "ollama": {"healthy": True},
            },
        }
        handler.send_json = MagicMock()

        handler.handle_requeue_runs({"run_ids": ["run-old-a", "run-old-b"]})

        payload = handler.send_json.call_args.args[0]
        assert payload["accepted"] == 1
        assert payload["rejected"] == 1
        assert payload["queued"][0]["source_run_id"] == "run-old-a"
        assert payload["errors"][0]["source_run_id"] == "run-old-b"
        mock_start_thread.assert_called_once()

    @patch("services.orchestrator.main._start_pipeline_thread")
    def test_handle_requeue_runs_dry_run_does_not_start_threads(self, mock_start_thread):
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.runner = MagicMock()
        handler.runner.build_requeue_plan.return_value = {
            "source_run_id": "run-old",
            "new_run_id": "run-new",
            "strategy": "rerun_query",
            "stages": 5,
            "stage_names": [
                "discovery",
                "analyzer",
                "extractor",
                "validator",
                "codegen",
            ],
            "params": {
                "query": "quant finance topic",
                "topic": None,
                "paper_id": None,
                "max_papers": 10,
                "max_formulas": 50,
                "force": False,
                "requeue_of": "run-old",
                "requeue_strategy": "rerun_query",
                "requeue_source_status": "partial",
                "requeue_requested_at": "2026-03-10T12:00:00+00:00",
                "requeue_source_stages_completed": 1,
                "requeue_source_stages_requested": 5,
                "requeue_source_failed_stage": "analyzer",
            },
        }
        handler.runner.check_external_health.return_value = {
            "all_healthy": True,
            "deps": {
                "cas": {"healthy": True},
                "rag": {"healthy": True},
                "ollama": {"healthy": True},
            },
        }
        handler.send_json = MagicMock()

        handler.handle_requeue_runs({"run_id": "run-old", "dry_run": True})

        payload = handler.send_json.call_args.args[0]
        assert payload["status"] == "dry_run"
        assert payload["accepted"] == 1
        mock_start_thread.assert_not_called()

    def test_handle_search_github_invalid_input(self):
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.send_error_json = MagicMock()
        # Missing paper_id
        res = handler.handle_search_github({})
        assert res is None
        handler.send_error_json.assert_called()

    def test_handle_delete_notation_not_found(self, initialized_db):
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.db_path = str(initialized_db)
        handler.send_error_json = MagicMock()
        
        res = handler.handle_delete_notation({"name": "nonexistent"})
        assert res is None
        handler.send_error_json.assert_called_once()


class TestPipelineRunnerAdvanced:
    """Tests for PipelineRunner's advanced logic (retries, batching, cleanup, health)."""

    def test_check_external_health_all_ok(self, initialized_db):
        runner = PipelineRunner(initialized_db)
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock(status_code=200)
            mock_get.return_value = mock_resp
            
            res = runner.check_external_health()
            assert res["all_healthy"] is True
            assert res["deps"]["cas"]["healthy"] is True
            assert res["deps"]["rag"]["healthy"] is True
            assert res["deps"]["ollama"]["healthy"] is True
            assert mock_get.call_count == 3

    def test_check_external_health_one_fail(self, initialized_db):
        runner = PipelineRunner(initialized_db)
        with patch("requests.get") as mock_get:
            # cas ok, rag fail, ollama ok
            resp_ok = MagicMock(status_code=200)
            resp_fail = MagicMock(status_code=500)
            mock_get.side_effect = [resp_ok, resp_fail, resp_ok]
            
            res = runner.check_external_health()
            assert res["all_healthy"] is False
            assert res["deps"]["cas"]["healthy"] is True
            assert res["deps"]["rag"]["healthy"] is False
            assert res["deps"]["ollama"]["healthy"] is True

    def test_get_services_health_all_ok(self, initialized_db):
        runner = PipelineRunner(initialized_db)
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock(status_code=200)
            mock_resp.json.return_value = {"status": "ok"}
            mock_get.return_value = mock_resp
            
            res = runner.get_services_health()
            assert res["all_healthy"] is True
            assert len(res["services"]) == 5
            for name in ["discovery", "analyzer", "extractor", "validator", "codegen"]:
                assert res["services"][name]["status"] == "ok"

    def test_get_services_health_one_fail(self, initialized_db):
        runner = PipelineRunner(initialized_db)
        with patch("requests.get") as mock_get:
            # 5 service checks + 3 external checks = 8 calls
            # Let's make analyzer fail (2nd service)
            resp_ok = MagicMock(status_code=200)
            resp_ok.json.return_value = {"status": "ok"}
            resp_fail = MagicMock(status_code=500)
            
            # Service calls: discovery, analyzer, extractor, validator, codegen
            # External calls: cas, rag, ollama
            mock_get.side_effect = [
                resp_ok, resp_fail, resp_ok, resp_ok, resp_ok, # services
                resp_ok, resp_ok, resp_ok                      # external
            ]
            
            res = runner.get_services_health()
            assert res["all_healthy"] is False
            assert res["services"]["discovery"]["status"] == "ok"
            assert res["services"]["analyzer"]["status"] == "error"
            assert res["services"]["extractor"]["status"] == "ok"

    @patch("requests.post")
    def test_call_service_with_retry_success_after_failure(self, mock_post, initialized_db):
        runner = PipelineRunner(initialized_db)
        runner.retry_max = 2
        runner.retry_backoff = 0.1
        
        # 1st fail (500), 2nd success
        resp_500 = MagicMock(status_code=500, text="Internal Error")
        resp_200 = MagicMock(status_code=200)
        resp_200.json.return_value = {"ok": True}
        mock_post.side_effect = [resp_500, resp_200]
        
        with patch("time.sleep"): # avoid actual sleeping
            res = runner._call_service_with_retry("http://test", {})
            assert res == {"ok": True}
            assert mock_post.call_count == 2

    @patch("requests.post")
    def test_call_service_with_retry_exhausted(self, mock_post, initialized_db):
        runner = PipelineRunner(initialized_db)
        runner.retry_max = 1
        runner.retry_backoff = 0.1
        
        mock_post.return_value = MagicMock(status_code=500, text="Continuous Error")
        
        with patch("time.sleep"):
            with pytest.raises(ServiceError, match="HTTP 500"):
                runner._call_service_with_retry("http://test", {})
        assert mock_post.call_count == 2

    @patch("requests.post")
    def test_call_service_no_retry_on_4xx(self, mock_post, initialized_db):
        runner = PipelineRunner(initialized_db)
        mock_post.return_value = MagicMock(status_code=400, text="Bad Request")
        mock_post.return_value.json.return_value = {"error": "validation failed"}
        
        with pytest.raises(ServiceError, match="HTTP 400: validation failed"):
            runner._call_service_with_retry("http://test", {})
        assert mock_post.call_count == 1

    def test_merge_batch_results_empty(self):
        """Empty batch results returns default structure."""
        merged = PipelineRunner._merge_batch_results([], "validator")
        assert merged["service"] == "validator"
        assert merged["formulas_processed"] == 0
        assert merged["success"] is True

    def test_merge_batch_results_single(self):
        """Single batch result is returned as is (with iterations)."""
        batch = [{"formulas_processed": 5, "success": True}]
        merged = PipelineRunner._merge_batch_results(batch, "validator")
        assert merged["formulas_processed"] == 5
        assert merged["batch_iterations"] == 1

    def test_merge_batch_results_validator(self):
        batch = [
            {"formulas_processed": 10, "formulas_valid": 8, "formulas_invalid": 2},
            {"formulas_processed": 5, "formulas_valid": 4, "formulas_invalid": 1},
        ]
        merged = PipelineRunner._merge_batch_results(batch, "validator")
        assert merged["formulas_processed"] == 15
        assert merged["formulas_valid"] == 12
        assert merged["formulas_invalid"] == 3
        assert merged["batch_iterations"] == 2

    def test_merge_batch_results_codegen_complex(self):
        """Test merging codegen results with mixed languages and errors."""
        batch = [
            {
                "formulas_processed": 1,
                "code_generated": {"python": 1, "c99": 1},
                "errors": [],
                "explanations_generated": 2,
            },
            {
                "formulas_processed": 2,
                "code_generated": {"python": 1, "rust": 1},
                "errors": ["some error"],
                "explanations_generated": 1,
            },
        ]
        merged = PipelineRunner._merge_batch_results(batch, "codegen")
        assert merged["formulas_processed"] == 3
        assert merged["code_generated"]["python"] == 2
        assert merged["code_generated"]["c99"] == 1
        assert merged["code_generated"]["rust"] == 1
        assert merged["explanations_generated"] == 3
        assert merged["errors"] == ["some error"]
        assert merged["batch_iterations"] == 2

    def test_cleanup_stuck_runs(self, initialized_db):
        db_path = str(initialized_db)
        runner = PipelineRunner(db_path)
        
        # Insert a stuck run
        with transaction(db_path) as conn:
            conn.execute(
                "INSERT INTO pipeline_runs (run_id, status, params, stages_requested) "
                "VALUES ('stuck-1', 'running', '{}', 5)"
            )
        
        count = runner.cleanup_stuck_runs()
        assert count == 1
        
        status = runner.get_run_status("stuck-1")
        assert status["status"] == "failed"
        assert "orphaned" in status["errors"][0]

    def test_get_run_status_not_found(self, initialized_db):
        runner = PipelineRunner(initialized_db)
        assert runner.get_run_status("nonexistent") is None

    @patch("requests.post")
    def test_run_with_service_error(self, mock_post, initialized_db):
        db_path = str(initialized_db)
        runner = PipelineRunner(db_path)
        runner.timeout = 0.1
        runner.retry_max = 1  # Lower retries for test speed
        
        # Discovery succeeds, but Analyzer fails
        resp_ok = MagicMock(status_code=200)
        resp_ok.json.return_value = {"papers_found": 1}
        resp_fail = MagicMock(status_code=500, text="Internal Server Error")
        
        # Discovery (1) + Analyzer (1 + 1 retry) = 3 calls
        mock_post.side_effect = [resp_ok, resp_fail, resp_fail]
        
        with patch("services.orchestrator.pipeline.time.sleep"):
            res = runner.run(query="test", stages=2)
            assert res["status"] == "partial"
            assert res["stages_completed"] == 1
            assert "analyzer: HTTP 500" in res["errors"][0]

    @patch("requests.post")
    def test_scoped_run_analyzer_timeout_skips_downstream_without_retry_amplification(
        self, mock_post, initialized_db
    ):
        db_path = str(initialized_db)
        runner = PipelineRunner(db_path)
        runner.timeout = 0.1
        runner.retry_max = 3

        resp_ok = MagicMock(status_code=200)
        resp_ok.json.return_value = {"papers_found": 1}
        mock_post.side_effect = [resp_ok, requests.Timeout("Read timed out")]

        with patch("services.orchestrator.pipeline.time.sleep"):
            res = runner.run(query="test", stages=5)

        assert res["status"] == "partial"
        assert res["stages_completed"] == 1
        assert mock_post.call_count == 2
        assert "analyzer: Timeout" in res["errors"][0]
        _assert_stage_skipped(res, "extractor", "analyzer")
        _assert_stage_skipped(res, "validator", "analyzer")
        _assert_stage_skipped(res, "codegen", "analyzer")

    def test_run_skips_stage_no_params(self, initialized_db):
        runner = PipelineRunner(str(initialized_db))
        # paper_id provided but no stages left (e.g. if paper was codegen already)
        with patch.object(PipelineRunner, "_get_paper_stage", return_value="codegen"):
            res = runner.run(paper_id=1)
            assert res["stages_completed"] == 0
            assert res["status"] == "completed"

    @patch("services.orchestrator.pipeline.PipelineRunner._update_run_record", side_effect=Exception("DB Error"))
    @patch("services.orchestrator.pipeline.PipelineRunner._call_service_with_retry")
    def test_run_persistence_failure_not_fatal(self, mock_call, mock_update, initialized_db):
        runner = PipelineRunner(str(initialized_db))
        mock_call.return_value = {"ok": True}
        # Should not raise
        res = runner.run(query="q", stages=1)
        assert res["status"] == "completed"


    @patch("urllib.request.urlopen")
    def test_query_rag_success(self, mock_open):
        from services.orchestrator.main import _query_rag
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"answer": "based"}).encode()
        mock_resp.__enter__.return_value = mock_resp
        mock_open.return_value = mock_resp
        
        res = _query_rag("test", "hybrid")
        assert res["answer"] == "based"

    @patch("urllib.request.urlopen", side_effect=Exception("RAG Down"))
    def test_query_rag_failure(self, mock_open):
        from services.orchestrator.main import _query_rag
        with pytest.raises(Exception, match="RAG Down"):
            _query_rag("test", "mix")


class TestPipelineAsync:
    """Tests for async pipeline runner helper."""

    @patch("services.orchestrator.main.notify_pipeline_result")
    def test_run_pipeline_async_failure(self, mock_notify):
        from services.orchestrator.main import _run_pipeline_async
        runner = MagicMock()
        runner.run.side_effect = Exception("Async crash")
        
        # Should catch exception and log it (implicitly covered)
        _run_pipeline_async(runner, "run-123")
        mock_notify.assert_not_called()
class TestOrchestratorMain:
    """Tests for orchestrator service entry point."""

    @patch("services.orchestrator.main.BaseService")
    @patch("services.orchestrator.main.load_config")
    @patch("services.orchestrator.main.init_db")
    @patch("services.orchestrator.main.create_scheduler")
    def test_main_startup_and_shutdown(self, mock_sched, mock_init, mock_load, mock_svc, initialized_db):
        from services.orchestrator.main import main
        mock_load.return_value = MagicMock(port=8775, db_path=str(initialized_db))
        
        # Test shutdown logic by making run() raise KeyboardInterrupt
        mock_svc.return_value.run.side_effect = KeyboardInterrupt()
        
        with patch.dict(os.environ, {"RP_ORCHESTRATOR_CRON_ENABLED": "true"}):
            try:
                main()
            except KeyboardInterrupt:
                pass
            
        mock_init.assert_called_once()
        mock_sched.return_value.start.assert_called_once()
        mock_sched.return_value.shutdown.assert_called_once()

    @patch("services.orchestrator.main.BaseService")
    @patch("services.orchestrator.main.load_config")
    @patch("services.orchestrator.main.init_db")
    @patch("services.orchestrator.main.create_scheduler")
    def test_main_startup_cron_disabled(self, mock_sched, mock_init, mock_load, mock_svc, initialized_db):
        from services.orchestrator.main import main
        mock_load.return_value = MagicMock(port=8775, db_path=str(initialized_db))
        mock_sched.return_value = None
        
        with patch.dict(os.environ, {"RP_ORCHESTRATOR_CRON_ENABLED": "false"}):
            main()
            
        mock_init.assert_called_once()
        mock_svc.return_value.run.assert_called_once()
        mock_sched.assert_called_once()

    @patch("services.orchestrator.main.BaseService")
    @patch("services.orchestrator.main.load_config")
    @patch("services.orchestrator.main.init_db")
    @patch("services.orchestrator.main.create_scheduler")
    @patch("services.orchestrator.main._resume_stuck_runs", return_value=(2, 1))
    def test_main_resumes_stuck_runs_when_enabled(
        self, mock_resume, mock_sched, mock_init, mock_load, mock_svc, initialized_db
    ):
        from services.orchestrator.main import main

        mock_load.return_value = MagicMock(port=8775, db_path=str(initialized_db))
        mock_sched.return_value = None

        with patch.dict(os.environ, {"RP_ORCHESTRATOR_RESUME_STUCK_RUNS": "true"}):
            main()

        mock_init.assert_called_once()
        mock_resume.assert_called_once()
        mock_svc.return_value.run.assert_called_once()

    @patch("services.orchestrator.main.BaseService")
    @patch("services.orchestrator.main.load_config")
    @patch("services.orchestrator.main.init_db")
    @patch("services.orchestrator.main.create_scheduler")
    @patch("services.orchestrator.pipeline.PipelineRunner.cleanup_stuck_runs", return_value=3)
    @patch("services.orchestrator.main._resume_stuck_runs")
    def test_main_cleans_stuck_runs_when_resume_disabled(
        self,
        mock_resume,
        mock_cleanup,
        mock_sched,
        mock_init,
        mock_load,
        mock_svc,
        initialized_db,
    ):
        from services.orchestrator.main import main

        mock_load.return_value = MagicMock(port=8775, db_path=str(initialized_db))
        mock_sched.return_value = None

        with patch.dict(os.environ, {"RP_ORCHESTRATOR_RESUME_STUCK_RUNS": "false"}):
            main()

        mock_init.assert_called_once()
        mock_resume.assert_not_called()
        mock_cleanup.assert_called_once()
        mock_svc.return_value.run.assert_called_once()


class TestPipelineAsync:
    """Tests for async pipeline runner helper."""

    @patch("services.orchestrator.main.notify_pipeline_result")
    def test_run_pipeline_async_failure(self, mock_notify):
        from services.orchestrator.main import _run_pipeline_async
        runner = MagicMock()
        runner.run.side_effect = Exception("Async crash")
        
        _run_pipeline_async(runner, "run-123")
        mock_notify.assert_not_called()

    @patch("services.orchestrator.main.threading.Thread")
    def test_resume_stuck_runs_spawns_threads(self, mock_thread):
        from services.orchestrator.main import _resume_stuck_runs

        runner = MagicMock()
        runner.get_stuck_runs.return_value = [
            {
                "run_id": "run-a",
                "params": {
                    "query": "test",
                    "topic": None,
                    "paper_id": None,
                    "max_papers": 10,
                    "max_formulas": 50,
                    "force": False,
                },
                "stages_requested": 5,
            }
        ]
        runner.fail_runs.return_value = 0

        resumed, failed = _resume_stuck_runs(runner)

        assert resumed == 1
        assert failed == 0
        mock_thread.assert_called_once()
        runner.fail_runs.assert_called_once_with(
            [],
            "Marked as failed: orphaned at service restart but not resumable",
        )

    @patch("services.orchestrator.main.threading.Thread")
    def test_resume_stuck_runs_marks_invalid_rows_failed(self, mock_thread):
        from services.orchestrator.main import _resume_stuck_runs

        runner = MagicMock()
        runner.get_stuck_runs.return_value = [
            {"run_id": "run-bad", "params": None, "stages_requested": 5}
        ]
        runner.fail_runs.return_value = 1

        resumed, failed = _resume_stuck_runs(runner)

        assert resumed == 0
        assert failed == 1
        mock_thread.assert_not_called()
        runner.fail_runs.assert_called_once_with(
            ["run-bad"],
            "Marked as failed: orphaned at service restart but not resumable",
        )


    def test_handle_github_repos_no_paper_id(self, initialized_db):
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.db_path = str(initialized_db)
        handler.path = "/github-repos"
        handler.send_error_json = MagicMock()
        
        res = handler.handle_github_repos()
        assert res is None
        handler.send_error_json.assert_called_once()

    def test_handle_add_notation_missing_fields(self, initialized_db):
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.send_error_json = MagicMock()
        res = handler.handle_add_notation({"name": "X"})
        assert res is None
        handler.send_error_json.assert_called_once()

    def test_handle_delete_notation_success(self, initialized_db):
        db_path = str(initialized_db)
        with transaction(db_path) as conn:
            conn.execute("INSERT INTO custom_notations (name, body) VALUES ('X', 'Y')")
        
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.db_path = db_path
        res = handler.handle_delete_notation({"name": "X"})
        assert res["success"] is True

    def test_handle_delete_notation_not_found(self, initialized_db):
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.db_path = str(initialized_db)
        handler.send_error_json = MagicMock()
        
        res = handler.handle_delete_notation({"name": "nonexistent"})
        assert res is None
        handler.send_error_json.assert_called_once()


    def test_handle_delete_notation_missing_fields(self, initialized_db):
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.send_error_json = MagicMock()
        # No 'name' in data
        res = handler.handle_delete_notation({})
        assert res is None
        handler.send_error_json.assert_called_once()

    @patch("services.orchestrator.main.notify")
    @patch("services.orchestrator.main.OrchestratorHandler.runner")
    def test_cron_run_failure(self, mock_runner, mock_notify):
        from services.orchestrator.main import _cron_run
        OrchestratorHandler.runner = MagicMock()
        OrchestratorHandler.runner.run.side_effect = Exception("Cron crash")
        
        with patch.dict(os.environ, {"RP_ORCHESTRATOR_CRON_ENABLED": "true"}):
            _cron_run()
            mock_notify.assert_called()

    @patch("services.orchestrator.main.notify_pipeline_result")
    @patch("services.orchestrator.main.OrchestratorHandler.runner")
    def test_cron_run_success(self, mock_runner, mock_notify):
        from services.orchestrator.main import _cron_run
        OrchestratorHandler.runner = MagicMock()
        result = {
            "status": "completed",
            "stages_completed": 5,
            "stages_requested": 5,
        }
        OrchestratorHandler.runner.run.return_value = result

        with patch.dict(os.environ, {"RP_ORCHESTRATOR_CRON_ENABLED": "true"}):
            _cron_run()
            mock_notify.assert_called_once_with(result)


# ---------------------------------------------------------------------------
# Mutation-killing tests: constants, defaults, run() internals
# ---------------------------------------------------------------------------


from services.orchestrator.pipeline import (
    DB_STAGE_INDEX,
    EXTERNAL_DEPS,
    STAGE_EXTERNAL_DEPS,
)


class TestPipelineConstants:
    """Pin module-level constants to kill constant-mutation survivors."""

    def test_external_deps_names(self):
        names = [d[0] for d in EXTERNAL_DEPS]
        assert names == ["cas", "rag", "ollama"]

    def test_external_deps_default_urls(self, clean_env):
        # Re-import to get defaults without env override
        deps = [
            ("cas", "http://localhost:8769", "/health"),
            ("rag", "http://localhost:8767", "/health"),
            ("ollama", "http://localhost:11434", "/"),
        ]
        for expected, actual in zip(deps, EXTERNAL_DEPS):
            assert actual[0] == expected[0], f"name mismatch: {actual[0]}"
            assert expected[2] == actual[2], f"health path mismatch for {actual[0]}"

    def test_stage_external_deps_mapping(self):
        assert STAGE_EXTERNAL_DEPS == {
            "extractor": ["rag"],
            "validator": ["cas"],
        }

    def test_db_stage_index_values(self):
        assert DB_STAGE_INDEX == {
            "discovered": 0,
            "analyzed": 1,
            "extracted": 2,
            "validated": 3,
            "codegen": 4,
        }

    def test_stage_params_discovery_mapping(self):
        assert STAGE_PARAMS["discovery"] == {"query": "query", "max_papers": "max_results"}

    def test_stage_params_analyzer_mapping(self):
        assert STAGE_PARAMS["analyzer"] == {
            "paper_id": "paper_id", "max_papers": "max_papers", "force": "force",
        }

    def test_stage_params_validator_mapping(self):
        assert STAGE_PARAMS["validator"] == {
            "paper_id": "paper_id", "max_formulas": "max_formulas", "force": "force",
        }

    def test_stage_params_codegen_mapping(self):
        assert STAGE_PARAMS["codegen"] == {
            "paper_id": "paper_id", "max_formulas": "max_formulas", "force": "force",
        }

    def test_stage_params_extractor_mapping(self):
        assert STAGE_PARAMS["extractor"] == {
            "paper_id": "paper_id", "max_papers": "max_papers", "force": "force",
        }


class TestPipelineRunnerInit:
    """Test __init__ reads env vars with correct defaults."""

    def test_default_timeout(self, clean_env, tmp_path):
        runner = PipelineRunner(tmp_path / "test.db")
        assert runner.timeout == 300

    def test_default_retry_max(self, clean_env, tmp_path):
        runner = PipelineRunner(tmp_path / "test.db")
        assert runner.retry_max == 3

    def test_default_retry_backoff(self, clean_env, tmp_path):
        runner = PipelineRunner(tmp_path / "test.db")
        assert runner.retry_backoff == 4.0

    def test_env_override_timeout(self, tmp_path):
        with patch.dict(os.environ, {"RP_ORCHESTRATOR_TIMEOUT": "60"}):
            runner = PipelineRunner(tmp_path / "test.db")
            assert runner.timeout == 60

    def test_env_override_retry_max(self, tmp_path):
        with patch.dict(os.environ, {"RP_ORCHESTRATOR_RETRY_MAX": "5"}):
            runner = PipelineRunner(tmp_path / "test.db")
            assert runner.retry_max == 5

    def test_env_override_retry_backoff(self, tmp_path):
        with patch.dict(os.environ, {"RP_ORCHESTRATOR_RETRY_BACKOFF": "2.0"}):
            runner = PipelineRunner(tmp_path / "test.db")
            assert runner.retry_backoff == 2.0

    def test_codegen_stage_timeout_default(self, clean_env):
        assert PipelineRunner.STAGE_TIMEOUTS.get("codegen") == 900

    def test_analyzer_stage_timeout_default(self, clean_env):
        assert PipelineRunner.STAGE_TIMEOUTS.get("analyzer") == 1800

    def test_instance_stage_timeout_defaults(self, clean_env, tmp_path):
        runner = PipelineRunner(tmp_path / "test.db")
        assert runner.STAGE_TIMEOUTS["analyzer"] == 1800
        assert runner.STAGE_TIMEOUTS["codegen"] == 900

    def test_env_override_analyzer_stage_timeout(self, tmp_path):
        with patch.dict(os.environ, {"RP_ORCHESTRATOR_ANALYZER_TIMEOUT": "600"}):
            runner = PipelineRunner(tmp_path / "test.db")
            assert runner.STAGE_TIMEOUTS["analyzer"] == 600

    def test_db_path_stored_as_string(self, tmp_path):
        runner = PipelineRunner(tmp_path / "test.db")
        assert isinstance(runner.db_path, str)


class TestRunInternals:
    """Tests that pin run() internals to kill mutation survivors."""

    def setup_method(self):
        self.runner = PipelineRunner.__new__(PipelineRunner)
        self.runner.db_path = ":memory:"
        self.runner.timeout = 5
        self.runner.retry_max = 0
        self.runner.retry_backoff = 1.0
        self.runner.STAGE_TIMEOUTS = {"analyzer": 1800, "codegen": 900}

    @patch.object(PipelineRunner, "_call_service_with_retry")
    def test_run_params_dict_keys(self, mock_call):
        """Verify the params dict passed internally has the right keys."""
        mock_call.return_value = {"ok": True}
        result = self.runner.run(
            query="q", paper_id=7, stages=1, max_papers=20, max_formulas=100, force=True
        )
        # Check the params are correctly forwarded to _build_stage_params
        assert result["status"] == "completed"
        # Verify _call_service_with_retry was called with correct mapped params
        call_args = mock_call.call_args
        assert "query" in call_args[0][1] or "max_results" in call_args[0][1]

    @patch.object(PipelineRunner, "_call_service_with_retry")
    def test_run_default_args(self, mock_call):
        """Test run() with default arguments."""
        mock_call.return_value = {"ok": True}
        result = self.runner.run(query="q")
        assert result["stages_requested"] == 5
        assert result["stages_completed"] == 5

    @patch.object(PipelineRunner, "_call_service_with_retry")
    def test_run_custom_run_id(self, mock_call):
        """Pre-generated run_id should be used."""
        mock_call.return_value = {"ok": True}
        result = self.runner.run(query="q", stages=1, run_id="custom-123")
        assert result["run_id"] == "custom-123"

    @patch.object(PipelineRunner, "_call_service_with_retry")
    def test_run_stage_results_have_time_ms(self, mock_call):
        """Each stage result should have time_ms."""
        mock_call.return_value = {"ok": True}
        result = self.runner.run(query="q", stages=2)
        for stage_name in ("discovery", "analyzer"):
            assert "time_ms" in result["results"][stage_name]
            assert isinstance(result["results"][stage_name]["time_ms"], int)

    @patch.object(PipelineRunner, "_call_service_with_retry")
    def test_run_error_message_includes_stage_name(self, mock_call):
        """Error messages should include the stage name."""
        mock_call.side_effect = ServiceError("connection refused")
        result = self.runner.run(query="q", stages=1)
        assert "discovery" in result["errors"][0]
        assert "connection refused" in result["errors"][0]

    @patch.object(PipelineRunner, "_call_service_with_retry")
    def test_run_failed_stage_result_has_error_and_time(self, mock_call):
        """Failed stage results include error string and time_ms."""
        mock_call.side_effect = ServiceError("boom")
        result = self.runner.run(query="q", stages=1)
        stage_result = result["results"]["discovery"]
        assert "error" in stage_result
        assert "time_ms" in stage_result
        assert stage_result["error"] == "boom"

    @patch.object(PipelineRunner, "_call_service_with_retry")
    def test_run_has_failure_flag_logic(self, mock_call):
        """Verify has_failure drives status correctly."""
        # All succeed → completed
        mock_call.return_value = {"ok": True}
        result = self.runner.run(query="q", stages=2)
        assert result["status"] == "completed"

    @patch.object(PipelineRunner, "_call_service_with_retry")
    def test_batch_stage_iterates_until_zero(self, mock_call):
        """Batch stages (validator/codegen) iterate until formulas_processed=0."""
        mock_call.side_effect = [
            {"ok": True},  # discovery
            {"ok": True},  # analyzer
            {"ok": True},  # extractor
            {"formulas_processed": 5, "formulas_valid": 5, "formulas_invalid": 0},  # validator iter 1
            {"formulas_processed": 0},  # validator iter 2 → stop
            {"formulas_processed": 3, "code_generated": {"python": 3}, "errors": []},  # codegen iter 1
            {"formulas_processed": 0},  # codegen iter 2 → stop
        ]
        result = self.runner.run(query="q", stages=5)
        assert result["status"] == "completed"
        assert result["results"]["validator"]["formulas_processed"] == 5
        assert result["results"]["validator"]["batch_iterations"] == 2
        assert result["results"]["codegen"]["batch_iterations"] == 2

    @patch.object(PipelineRunner, "_call_service_with_retry")
    def test_non_batch_stage_single_call(self, mock_call):
        """Non-batch stages (discovery, analyzer, extractor) call service once."""
        mock_call.return_value = {"papers_found": 3}
        result = self.runner.run(query="q", stages=1)
        assert mock_call.call_count == 1
        assert "batch_iterations" not in result["results"]["discovery"]

    @patch.object(PipelineRunner, "_call_service_with_retry")
    def test_codegen_uses_stage_timeout(self, mock_call):
        """Codegen stage should use STAGE_TIMEOUTS override."""
        mock_call.return_value = {"ok": True}
        self.runner.STAGE_TIMEOUTS = {"analyzer": 1800, "codegen": 999}

        # Run just codegen via paper_id trick
        with patch.object(self.runner, "_get_paper_stage", return_value="validated"):
            self.runner.run(paper_id=1, stages=1)

        # Check timeout was passed
        _, kwargs = mock_call.call_args
        assert kwargs.get("timeout") == 999

    @patch.object(PipelineRunner, "_call_service_with_retry")
    def test_analyzer_uses_stage_timeout(self, mock_call):
        """Analyzer stage should use its dedicated timeout override."""
        mock_call.return_value = {"ok": True}
        self.runner.STAGE_TIMEOUTS = {"analyzer": 777, "codegen": 900}

        self.runner.run(query="q", stages=2)

        _, kwargs = mock_call.call_args_list[1]
        assert kwargs.get("timeout") == 777
        assert kwargs.get("retry_on_timeout") is False

    @patch.object(PipelineRunner, "_call_service_with_retry")
    def test_service_url_format(self, mock_call):
        """Services are called at http://localhost:{port}/process."""
        from services.orchestrator.pipeline import STAGE_ORDER

        mock_call.return_value = {"ok": True}
        self.runner.run(query="q", stages=1)
        url = mock_call.call_args[0][0]
        discovery_port = STAGE_ORDER[0][1]
        assert url == f"http://localhost:{discovery_port}/process"

    @patch.object(PipelineRunner, "_call_service_with_retry")
    def test_discovery_papers_found_tracked(self, mock_call):
        """papers_found from discovery is used for Prometheus metrics."""
        mock_call.return_value = {"papers_found": 7}
        result = self.runner.run(query="q", stages=1)
        assert result["results"]["discovery"]["papers_found"] == 7


class TestCallServiceInternals:
    """Pin _call_service_with_retry internals."""

    def setup_method(self):
        self.runner = PipelineRunner.__new__(PipelineRunner)
        self.runner.timeout = 30
        self.runner.retry_max = 2
        self.runner.retry_backoff = 4.0

    @patch("services.orchestrator.pipeline.time.sleep")
    @patch("services.orchestrator.pipeline.requests.post")
    def test_backoff_calculation(self, mock_post, mock_sleep):
        """Backoff is base ** attempt: 1, 4, 16..."""
        mock_post.return_value = MagicMock(status_code=500, text="error")
        with pytest.raises(ServiceError):
            self.runner._call_service_with_retry("http://test", {})
        # attempt=0: sleep(4.0**0)=1.0, attempt=1: sleep(4.0**1)=4.0
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(1.0)   # 4.0 ** 0
        mock_sleep.assert_any_call(4.0)   # 4.0 ** 1

    @patch("services.orchestrator.pipeline.requests.post")
    def test_custom_timeout_passed_to_requests(self, mock_post):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"ok": True}
        mock_post.return_value = mock_resp

        self.runner._call_service_with_retry("http://test", {}, timeout=42)
        _, kwargs = mock_post.call_args
        assert kwargs["timeout"] == 42

    @patch("services.orchestrator.pipeline.requests.post")
    def test_default_timeout_used_when_none(self, mock_post):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"ok": True}
        mock_post.return_value = mock_resp

        self.runner._call_service_with_retry("http://test", {})
        _, kwargs = mock_post.call_args
        assert kwargs["timeout"] == 30  # self.timeout

    @patch("services.orchestrator.pipeline.requests.post")
    def test_4xx_json_parse_error_uses_text(self, mock_post):
        """When 4xx response body is not JSON, use resp.text."""
        mock_resp = MagicMock(status_code=422)
        mock_resp.json.side_effect = ValueError("not json")
        mock_resp.text = "Unprocessable Entity"
        mock_post.return_value = mock_resp

        with pytest.raises(ServiceError, match="Unprocessable Entity"):
            self.runner._call_service_with_retry("http://test", {})

    @patch("services.orchestrator.pipeline.requests.post")
    def test_4xx_json_error_key_used(self, mock_post):
        """When 4xx response has JSON with 'error' key, use that."""
        mock_resp = MagicMock(status_code=400)
        mock_resp.json.return_value = {"error": "invalid paper_id"}
        mock_resp.text = '{"error": "invalid paper_id"}'
        mock_post.return_value = mock_resp

        with pytest.raises(ServiceError, match="invalid paper_id"):
            self.runner._call_service_with_retry("http://test", {})

    @patch("services.orchestrator.pipeline.time.sleep")
    @patch("services.orchestrator.pipeline.requests.post")
    def test_timeout_no_retry_when_disabled(self, mock_post, mock_sleep):
        mock_post.side_effect = requests.Timeout("Read timed out")
        self.runner.retry_max = 3

        with pytest.raises(ServiceError, match="Timeout after 30s"):
            self.runner._call_service_with_retry(
                "http://test", {}, retry_on_timeout=False
            )

        assert mock_post.call_count == 1
        mock_sleep.assert_not_called()

    @patch("services.orchestrator.pipeline.requests.post")
    def test_status_code_in_error_message(self, mock_post):
        """Error messages include the HTTP status code."""
        mock_resp = MagicMock(status_code=503)
        mock_resp.text = "Service Unavailable"
        mock_post.return_value = mock_resp
        self.runner.retry_max = 0

        with pytest.raises(ServiceError, match="HTTP 503"):
            self.runner._call_service_with_retry("http://test", {})

    @patch("services.orchestrator.pipeline.requests.post")
    def test_5xx_text_truncated_in_error(self, mock_post):
        """5xx error messages truncate response text to 200 chars."""
        long_text = "x" * 500
        mock_resp = MagicMock(status_code=500, text=long_text)
        mock_post.return_value = mock_resp
        self.runner.retry_max = 0

        with pytest.raises(ServiceError) as exc_info:
            self.runner._call_service_with_retry("http://test", {})
        # The error should contain truncated text
        assert len(str(exc_info.value)) < 300

    @patch("services.orchestrator.pipeline.requests.post")
    def test_connection_error_message(self, mock_post):
        mock_post.side_effect = requests.ConnectionError("refused")
        self.runner.retry_max = 0
        with pytest.raises(ServiceError, match="Connection refused"):
            self.runner._call_service_with_retry("http://test", {})

    @patch("services.orchestrator.pipeline.requests.post")
    def test_timeout_error_message(self, mock_post):
        mock_post.side_effect = requests.Timeout("timed out")
        self.runner.retry_max = 0
        with pytest.raises(ServiceError, match="Timeout after 30s"):
            self.runner._call_service_with_retry("http://test", {})


class TestGetPipelineStatus:
    """Unit tests for get_pipeline_status with real DB."""

    def test_empty_db(self, initialized_db):
        runner = PipelineRunner(str(initialized_db))
        status = runner.get_pipeline_status()
        assert status["papers_by_stage"] == {}
        assert status["formulas_by_stage"] == {}
        assert status["recent_errors"] == []

    def test_papers_by_stage(self, initialized_db):
        from shared.db import transaction
        db = str(initialized_db)
        with transaction(db) as conn:
            conn.execute("INSERT INTO papers (arxiv_id, title, stage) VALUES ('1', 'A', 'discovered')")
            conn.execute("INSERT INTO papers (arxiv_id, title, stage) VALUES ('2', 'B', 'discovered')")
            conn.execute("INSERT INTO papers (arxiv_id, title, stage) VALUES ('3', 'C', 'analyzed')")
        runner = PipelineRunner(db)
        status = runner.get_pipeline_status()
        assert status["papers_by_stage"]["discovered"] == 2
        assert status["papers_by_stage"]["analyzed"] == 1

    def test_recent_errors(self, initialized_db):
        from shared.db import transaction
        db = str(initialized_db)
        with transaction(db) as conn:
            conn.execute(
                "INSERT INTO papers (arxiv_id, title, stage, error) "
                "VALUES ('1', 'A', 'failed', 'connection timeout')"
            )
        runner = PipelineRunner(db)
        status = runner.get_pipeline_status()
        assert len(status["recent_errors"]) == 1
        err = status["recent_errors"][0]
        assert err["paper_id"] == 1
        assert err["stage"] == "failed"
        assert err["error"] == "connection timeout"
        assert "timestamp" in err


class TestRunPersistence:
    """Unit tests for run record CRUD."""

    def test_create_and_get_run(self, initialized_db):
        runner = PipelineRunner(str(initialized_db))
        runner._create_run_record("run-test-1", {"query": "test"}, 3)
        status = runner.get_run_status("run-test-1")
        assert status is not None
        assert status["run_id"] == "run-test-1"
        assert status["status"] == "running"
        assert status["stages_requested"] == 3
        assert status["params"]["query"] == "test"

    def test_update_run_record(self, initialized_db):
        runner = PipelineRunner(str(initialized_db))
        runner._create_run_record("run-test-2", {}, 5)
        runner._update_run_record("run-test-2", {
            "status": "completed",
            "results": {"discovery": {"papers_found": 3}},
            "errors": [],
            "stages_completed": 5,
        })
        status = runner.get_run_status("run-test-2")
        assert status["status"] == "completed"
        assert status["stages_completed"] == 5
        assert status["results"]["discovery"]["papers_found"] == 3
        assert status["errors"] == []

    def test_list_runs_ordered_by_recent(self, initialized_db):
        runner = PipelineRunner(str(initialized_db))
        runner._create_run_record("run-a", {}, 1)
        runner._create_run_record("run-b", {}, 2)
        runs = runner.list_runs(limit=10)
        assert len(runs) == 2
        # Most recent first
        assert runs[0]["run_id"] == "run-b"
        assert runs[1]["run_id"] == "run-a"

    def test_list_runs_respects_limit(self, initialized_db):
        runner = PipelineRunner(str(initialized_db))
        for i in range(5):
            runner._create_run_record(f"run-{i}", {}, 1)
        runs = runner.list_runs(limit=3)
        assert len(runs) == 3

    def test_list_runs_default_limit(self, initialized_db):
        runner = PipelineRunner(str(initialized_db))
        runs = runner.list_runs()
        assert isinstance(runs, list)

    def test_get_run_json_fields_parsed(self, initialized_db):
        runner = PipelineRunner(str(initialized_db))
        runner._create_run_record("run-json", {"key": "val"}, 1)
        runner._update_run_record("run-json", {
            "status": "completed",
            "results": {"a": 1},
            "errors": ["e1"],
            "stages_completed": 1,
        })
        status = runner.get_run_status("run-json")
        # JSON fields should be parsed into dicts/lists
        assert isinstance(status["params"], dict)
        assert isinstance(status["results"], dict)
        assert isinstance(status["errors"], list)

    def test_cleanup_stuck_runs_none(self, initialized_db):
        runner = PipelineRunner(str(initialized_db))
        count = runner.cleanup_stuck_runs()
        assert count == 0

    def test_cleanup_stuck_runs_marks_failed(self, initialized_db):
        from shared.db import transaction
        db = str(initialized_db)
        runner = PipelineRunner(db)
        with transaction(db) as conn:
            conn.execute(
                "INSERT INTO pipeline_runs (run_id, status, params, stages_requested) "
                "VALUES ('stuck-a', 'running', '{}', 3)"
            )
            conn.execute(
                "INSERT INTO pipeline_runs (run_id, status, params, stages_requested) "
                "VALUES ('stuck-b', 'running', '{}', 5)"
            )
            conn.execute(
                "INSERT INTO pipeline_runs (run_id, status, params, stages_requested) "
                "VALUES ('done-c', 'completed', '{}', 2)"
            )
        count = runner.cleanup_stuck_runs()
        assert count == 2
        # Verify they're marked failed
        a = runner.get_run_status("stuck-a")
        assert a["status"] == "failed"
        assert "orphaned" in a["errors"][0]
        # Completed run untouched
        c = runner.get_run_status("done-c")
        assert c["status"] == "completed"


class TestHealthCheckDetails:
    """Pin health check response structure."""

    @patch("services.orchestrator.pipeline.requests.get")
    def test_services_health_response_structure(self, mock_get, initialized_db):
        runner = PipelineRunner(str(initialized_db))
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"status": "ok"}
        mock_get.return_value = resp

        result = runner.get_services_health()
        assert "all_healthy" in result
        assert "services" in result
        assert "external" in result
        # Each service has port
        for name in ("discovery", "analyzer", "extractor", "validator", "codegen"):
            assert "port" in result["services"][name]

    @patch("services.orchestrator.pipeline.requests.get")
    def test_services_health_error_includes_status_code(self, mock_get, initialized_db):
        runner = PipelineRunner(str(initialized_db))
        resp_ok = MagicMock(status_code=200)
        resp_ok.json.return_value = {"status": "ok"}
        resp_err = MagicMock(status_code=502)
        # discovery ok, analyzer 502, rest ok + 3 external ok
        mock_get.side_effect = [resp_ok, resp_err, resp_ok, resp_ok, resp_ok, resp_ok, resp_ok, resp_ok]

        from services.orchestrator.pipeline import STAGE_ORDER

        result = runner.get_services_health()
        assert result["services"]["analyzer"]["status"] == "error"
        assert "502" in result["services"]["analyzer"]["error"]
        assert result["services"]["analyzer"]["port"] == STAGE_ORDER[1][1]

    @patch("services.orchestrator.pipeline.requests.get")
    def test_services_health_connection_error(self, mock_get, initialized_db):
        runner = PipelineRunner(str(initialized_db))
        resp_ok = MagicMock(status_code=200)
        resp_ok.json.return_value = {"status": "ok"}
        # discovery raises ConnectionError, rest ok + 3 external ok
        mock_get.side_effect = [
            requests.ConnectionError("refused"),
            resp_ok, resp_ok, resp_ok, resp_ok,
            resp_ok, resp_ok, resp_ok,
        ]
        result = runner.get_services_health()
        assert result["all_healthy"] is False
        assert result["services"]["discovery"]["status"] == "error"
        assert "refused" in result["services"]["discovery"]["error"]

    @patch("services.orchestrator.pipeline.requests.get")
    def test_external_health_url_and_healthy_fields(self, mock_get, initialized_db):
        runner = PipelineRunner(str(initialized_db))
        mock_get.return_value = MagicMock(status_code=200)
        result = runner.check_external_health()
        for name in ("cas", "rag", "ollama"):
            assert "url" in result["deps"][name]
            assert "healthy" in result["deps"][name]
            assert result["deps"][name]["healthy"] is True

    @patch("services.orchestrator.pipeline.requests.get")
    def test_external_health_connection_error_marks_unhealthy(self, mock_get, initialized_db):
        runner = PipelineRunner(str(initialized_db))
        resp_ok = MagicMock(status_code=200)
        mock_get.side_effect = [resp_ok, requests.ConnectionError("down"), resp_ok]
        result = runner.check_external_health()
        assert result["all_healthy"] is False
        assert result["deps"]["cas"]["healthy"] is True
        assert result["deps"]["rag"]["healthy"] is False
        assert result["deps"]["ollama"]["healthy"] is True

    @patch("services.orchestrator.pipeline.requests.get")
    def test_external_health_status_400_is_unhealthy(self, mock_get, initialized_db):
        runner = PipelineRunner(str(initialized_db))
        mock_get.return_value = MagicMock(status_code=400)
        result = runner.check_external_health()
        assert result["all_healthy"] is False
        for dep in result["deps"].values():
            assert dep["healthy"] is False

    @patch("services.orchestrator.pipeline.requests.get")
    def test_health_timeout_value(self, mock_get, initialized_db):
        """Health checks use timeout=5 for services, timeout=3 for external."""
        runner = PipelineRunner(str(initialized_db))
        mock_get.return_value = MagicMock(status_code=200)
        mock_get.return_value.json.return_value = {"status": "ok"}
        runner.get_services_health()
        # First 5 calls are service health (timeout=5), next 3 are external (timeout=3)
        for call in mock_get.call_args_list[:5]:
            assert call[1]["timeout"] == 5
        for call in mock_get.call_args_list[5:]:
            assert call[1]["timeout"] == 3
