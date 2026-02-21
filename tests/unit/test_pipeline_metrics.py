"""Unit tests for orchestrator pipeline Prometheus metrics.

Verifies that PipelineRunner.run() correctly increments/decrements
all pipeline metrics: active gauge, run duration, stage counters,
papers processed, formulas validated.

Uses before/after pattern for metric assertions since Prometheus
counters are global singletons that accumulate across tests.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from prometheus_client import REGISTRY

from services.orchestrator.pipeline import PipelineRunner, ServiceError


def _sample(name: str, labels: dict | None = None) -> float:
    """Read a metric value from the global REGISTRY."""
    val = REGISTRY.get_sample_value(name, labels or {})
    return val if val is not None else 0.0


def _make_runner() -> PipelineRunner:
    """Create a PipelineRunner without calling __init__ (avoids DB)."""
    runner = PipelineRunner.__new__(PipelineRunner)
    runner.db_path = ":memory:"
    runner.timeout = 5
    runner.retry_max = 0
    runner.retry_backoff = 1.0
    return runner


class TestPipelineRunsActiveGauge:
    """Tests for PIPELINE_RUNS_ACTIVE gauge (inc at start, dec in finally)."""

    @patch.object(PipelineRunner, "_update_run_record")
    @patch.object(PipelineRunner, "_create_run_record")
    @patch.object(PipelineRunner, "_call_service_with_retry")
    def test_gauge_zero_after_successful_run(self, mock_call, mock_create, mock_update):
        mock_call.return_value = {"papers_found": 3}

        before = _sample("pepers_pipeline_runs_active")
        runner = _make_runner()
        runner.run(query="test", stages=1)
        after = _sample("pepers_pipeline_runs_active")

        # Gauge should be back to same value (inc then dec)
        assert after == before

    @patch.object(PipelineRunner, "_update_run_record")
    @patch.object(PipelineRunner, "_create_run_record")
    @patch.object(PipelineRunner, "_call_service_with_retry")
    def test_gauge_decrements_on_error(self, mock_call, mock_create, mock_update):
        mock_call.side_effect = ServiceError("all down")

        before = _sample("pepers_pipeline_runs_active")
        runner = _make_runner()
        runner.run(query="test", stages=1)
        after = _sample("pepers_pipeline_runs_active")

        # Gauge should still be back to same value even on failure
        assert after == before


class TestPipelineRunDuration:
    """Tests for PIPELINE_RUN_DURATION histogram."""

    @patch.object(PipelineRunner, "_update_run_record")
    @patch.object(PipelineRunner, "_create_run_record")
    @patch.object(PipelineRunner, "_call_service_with_retry")
    def test_run_records_duration(self, mock_call, mock_create, mock_update):
        mock_call.return_value = {"ok": True}

        before_sum = _sample("pepers_pipeline_run_duration_seconds_sum")
        before_count = _sample("pepers_pipeline_run_duration_seconds_count")

        runner = _make_runner()
        runner.run(query="test", stages=1)

        after_sum = _sample("pepers_pipeline_run_duration_seconds_sum")
        after_count = _sample("pepers_pipeline_run_duration_seconds_count")

        assert after_count == before_count + 1
        assert after_sum > before_sum


class TestStageCompleted:
    """Tests for STAGE_COMPLETED counter with stage/result labels."""

    @patch.object(PipelineRunner, "_update_run_record")
    @patch.object(PipelineRunner, "_create_run_record")
    @patch.object(PipelineRunner, "_call_service_with_retry")
    def test_stage_success_increments(self, mock_call, mock_create, mock_update):
        mock_call.return_value = {"papers_found": 3}

        labels = {"stage": "discovery", "result": "success"}
        before = _sample("pepers_stage_completed_total", labels)

        runner = _make_runner()
        runner.run(query="test", stages=1)

        after = _sample("pepers_stage_completed_total", labels)
        assert after == before + 1

    @patch.object(PipelineRunner, "_update_run_record")
    @patch.object(PipelineRunner, "_create_run_record")
    @patch.object(PipelineRunner, "_call_service_with_retry")
    def test_stage_failure_records_failure_result(self, mock_call, mock_create, mock_update):
        mock_call.side_effect = ServiceError("Discovery down")

        labels = {"stage": "discovery", "result": "failure"}
        before = _sample("pepers_stage_completed_total", labels)

        runner = _make_runner()
        runner.run(query="test", stages=1)

        after = _sample("pepers_stage_completed_total", labels)
        assert after == before + 1

    @patch.object(PipelineRunner, "_update_run_record")
    @patch.object(PipelineRunner, "_create_run_record")
    @patch.object(PipelineRunner, "_call_service_with_retry")
    def test_skipped_stage_records_skipped(self, mock_call, mock_create, mock_update):
        """Stages with no applicable params are recorded as skipped."""
        mock_call.return_value = {"ok": True}

        # Run with paper_id=None and query=None (batch mode).
        # Discovery stage in batch mode: _build_stage_params("discovery", ...) with
        # query=None returns {"max_results": 10} which is non-empty, so stages won't
        # be skipped. Instead, run with paper_id-only mode from a late stage where
        # discovery has no params.
        # Actually, the simplest way: use paper_id=42 mode which skips discovery.
        # But _get_paper_stage needs to be mocked. Let's mock _resolve_stages to
        # return all 5 stages, and mock _build_stage_params to return empty for one.
        runner = _make_runner()

        labels = {"stage": "discovery", "result": "skipped"}
        before = _sample("pepers_stage_completed_total", labels)

        with patch.object(runner, "_build_stage_params") as mock_params:
            # discovery returns empty (skipped), analyzer returns params
            mock_params.side_effect = [
                {},  # discovery -> skipped
                {"paper_id": 42},  # analyzer -> runs
            ]
            with patch.object(runner, "_resolve_stages") as mock_resolve:
                mock_resolve.return_value = [("discovery", 8770), ("analyzer", 8771)]
                runner.run(query="test", stages=2)

        after = _sample("pepers_stage_completed_total", labels)
        assert after == before + 1


class TestStageDuration:
    """Tests for STAGE_DURATION histogram."""

    @patch.object(PipelineRunner, "_update_run_record")
    @patch.object(PipelineRunner, "_create_run_record")
    @patch.object(PipelineRunner, "_call_service_with_retry")
    def test_stage_duration_recorded(self, mock_call, mock_create, mock_update):
        mock_call.return_value = {"papers_found": 3}

        labels = {"stage": "discovery"}
        before = _sample("pepers_stage_duration_seconds_count", labels)

        runner = _make_runner()
        runner.run(query="test", stages=1)

        after = _sample("pepers_stage_duration_seconds_count", labels)
        assert after == before + 1


class TestPapersProcessed:
    """Tests for PAPERS_PROCESSED counter."""

    @patch.object(PipelineRunner, "_update_run_record")
    @patch.object(PipelineRunner, "_create_run_record")
    @patch.object(PipelineRunner, "_call_service_with_retry")
    def test_papers_processed_increments(self, mock_call, mock_create, mock_update):
        mock_call.return_value = {"papers_found": 7}

        before = _sample("pepers_papers_processed_total")

        runner = _make_runner()
        runner.run(query="test", stages=1)

        after = _sample("pepers_papers_processed_total")
        assert after == before + 7


class TestFormulasValidated:
    """Tests for FORMULAS_VALIDATED counter."""

    @patch.object(PipelineRunner, "_update_run_record")
    @patch.object(PipelineRunner, "_create_run_record")
    @patch.object(PipelineRunner, "_call_service_with_retry")
    def test_formulas_validated_increments(self, mock_call, mock_create, mock_update):
        # Stages: discovery, analyzer, extractor, validator, codegen
        # We need validator to return formulas_processed
        mock_call.side_effect = [
            {"papers_found": 3},         # discovery
            {"analyzed": 3},             # analyzer
            {"extracted": 10},           # extractor
            {"formulas_processed": 5},   # validator (first batch, stops)
            {"formulas_processed": 0},   # validator (empty batch -> stops iteration)
            {"formulas_processed": 0},   # codegen (empty batch -> stops iteration)
        ]

        before = _sample("pepers_formulas_validated_total")

        runner = _make_runner()
        runner.run(query="test", stages=5)

        after = _sample("pepers_formulas_validated_total")
        assert after == before + 5
