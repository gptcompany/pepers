"""Unit tests for orchestrator service — pipeline dispatch, retry, scheduler."""

from __future__ import annotations

import os
import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from services.orchestrator.pipeline import (
    STAGE_ORDER,
    STAGE_PARAMS,
    PipelineRunner,
    ServiceError,
)
from services.orchestrator.scheduler import create_scheduler


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


# ---------------------------------------------------------------------------
# PipelineRunner._build_stage_params
# ---------------------------------------------------------------------------


class TestBuildStageParams:
    """Tests for parameter mapping to services."""

    def setup_method(self):
        self.runner = PipelineRunner.__new__(PipelineRunner)
        self.params = {
            "query": "kelly criterion",
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
        assert result == {"paper_id": 42, "max_papers": 10, "force": True}

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
            {"processed": 2},
            {"valid": 1},
            {"code_generated": {"c99": 1}},
        ]

        result = self.runner.run(query="test", stages=5)

        assert result["status"] == "partial"
        assert result["stages_completed"] == 4
        assert len(result["errors"]) == 1

    @patch.object(PipelineRunner, "_call_service_with_retry")
    def test_all_stages_fail(self, mock_call):
        mock_call.side_effect = ServiceError("all down")

        result = self.runner.run(query="test", stages=5)

        assert result["status"] == "failed"
        assert result["stages_completed"] == 0
        assert len(result["errors"]) == 5

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
        assert ports == [8770, 8771, 8772, 8773, 8774]

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
