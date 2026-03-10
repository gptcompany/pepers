"""Unit tests for RES-01: Stuck pipeline run cleanup at orchestrator startup."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from shared.db import init_db, transaction
from services.orchestrator.pipeline import PipelineRunner, RequeueError


@pytest.fixture
def db_path():
    """Create a temporary database with pipeline_runs table."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = str(Path(tmpdir) / "test.db")
        init_db(path)
        yield path


def _insert_run(
    db_path: str,
    run_id: str,
    status: str,
    started_minutes_ago: int = 0,
    *,
    params: str = "{}",
    stages_requested: int = 1,
    stages_completed: int = 0,
    results: str | None = None,
    errors: str | None = None,
) -> None:
    """Insert a pipeline run with a specific started_at offset."""
    with transaction(db_path) as conn:
        conn.execute(
            "INSERT INTO pipeline_runs "
            "(run_id, status, params, results, errors, stages_requested, "
            "stages_completed, started_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now', ?))",
            (
                run_id,
                status,
                params,
                results,
                errors,
                stages_requested,
                stages_completed,
                f"-{started_minutes_ago} minutes",
            ),
        )


class TestCleanupStuckRuns:
    """Tests for PipelineRunner.cleanup_stuck_runs()."""

    def test_cleans_all_running_on_startup(self, db_path):
        """All 'running' runs are marked as failed (orphaned by definition)."""
        _insert_run(db_path, "run-old", "running", started_minutes_ago=60)
        _insert_run(db_path, "run-recent", "running", started_minutes_ago=1)

        runner = PipelineRunner(db_path)
        cleaned = runner.cleanup_stuck_runs()

        assert cleaned == 2

        # Both should be failed
        for rid in ("run-old", "run-recent"):
            status = runner.get_run_status(rid)
            assert status is not None
            assert status["status"] == "failed"
            assert status["completed_at"] is not None
            assert "orphaned" in status["errors"][0].lower()

    def test_ignores_completed_runs(self, db_path):
        """Completed runs are not affected."""
        _insert_run(db_path, "run-done", "completed", started_minutes_ago=120)

        runner = PipelineRunner(db_path)
        cleaned = runner.cleanup_stuck_runs()

        assert cleaned == 0
        status = runner.get_run_status("run-done")
        assert status["status"] == "completed"

    def test_ignores_failed_runs(self, db_path):
        """Already-failed runs are not double-cleaned."""
        _insert_run(db_path, "run-failed", "failed", started_minutes_ago=30)

        runner = PipelineRunner(db_path)
        cleaned = runner.cleanup_stuck_runs()

        assert cleaned == 0

    def test_ignores_partial_runs(self, db_path):
        """Partial runs are not affected."""
        _insert_run(db_path, "run-partial", "partial", started_minutes_ago=30)

        runner = PipelineRunner(db_path)
        cleaned = runner.cleanup_stuck_runs()

        assert cleaned == 0

    def test_returns_zero_when_no_stuck_runs(self, db_path):
        """No stuck runs → returns 0."""
        runner = PipelineRunner(db_path)
        cleaned = runner.cleanup_stuck_runs()
        assert cleaned == 0

    def test_error_message_is_valid_json(self, db_path):
        """The errors field is valid JSON array."""
        _insert_run(db_path, "run-stuck", "running", started_minutes_ago=10)

        runner = PipelineRunner(db_path)
        runner.cleanup_stuck_runs()

        status = runner.get_run_status("run-stuck")
        assert isinstance(status["errors"], list)
        assert len(status["errors"]) == 1

    def test_get_stuck_runs_returns_running_runs_with_params(self, db_path):
        with transaction(db_path) as conn:
            conn.execute(
                "INSERT INTO pipeline_runs "
                "(run_id, status, params, stages_requested) "
                "VALUES (?, 'running', ?, ?)",
                ("run-resume", '{"query":"test","max_papers":10}', 5),
            )
            conn.execute(
                "INSERT INTO pipeline_runs "
                "(run_id, status, params, stages_requested) "
                "VALUES (?, 'completed', ?, ?)",
                ("run-done", "{}", 1),
            )

        runner = PipelineRunner(db_path)
        stuck = runner.get_stuck_runs()

        assert len(stuck) == 1
        assert stuck[0]["run_id"] == "run-resume"
        assert stuck[0]["params"]["query"] == "test"
        assert stuck[0]["stages_requested"] == 5

    def test_fail_runs_marks_only_selected_running_runs_failed(self, db_path):
        _insert_run(db_path, "run-a", "running", started_minutes_ago=10)
        _insert_run(db_path, "run-b", "running", started_minutes_ago=5)
        _insert_run(db_path, "run-c", "completed", started_minutes_ago=1)

        runner = PipelineRunner(db_path)
        updated = runner.fail_runs(["run-a"], "manual failure")

        assert updated == 1
        assert runner.get_run_status("run-a")["status"] == "failed"
        assert runner.get_run_status("run-b")["status"] == "running"
        assert runner.get_run_status("run-c")["status"] == "completed"


class TestBuildRequeuePlan:
    """Tests for safe requeue planning of terminal runs."""

    def test_builds_query_rerun_plan_for_partial_run(self, db_path):
        _insert_run(
            db_path,
            "run-query",
            "partial",
            params=(
                '{"query":"quant finance topic","topic":null,"paper_id":null,'
                '"max_papers":10,"max_formulas":50,"force":false}'
            ),
            stages_requested=5,
            stages_completed=1,
            results=(
                '{"discovery":{"papers_found":3},"analyzer":{"error":"timeout",'
                '"time_ms":300000}}'
            ),
            errors='["analyzer: timeout"]',
        )

        runner = PipelineRunner(db_path)
        plan = runner.build_requeue_plan("run-query")

        assert plan["source_run_id"] == "run-query"
        assert plan["strategy"] == "rerun_query"
        assert plan["stage_names"] == [
            "discovery",
            "analyzer",
            "extractor",
            "validator",
            "codegen",
        ]
        assert plan["params"]["query"] == "quant finance topic"
        assert plan["params"]["requeue_of"] == "run-query"
        assert plan["params"]["requeue_source_failed_stage"] == "analyzer"

    def test_builds_paper_resume_plan_from_current_stage(self, db_path):
        with transaction(db_path) as conn:
            conn.execute(
                "INSERT INTO papers (id, arxiv_id, title, stage) VALUES (?, ?, ?, ?)",
                (1, "2401.00001", "Test paper", "analyzed"),
            )

        _insert_run(
            db_path,
            "run-paper",
            "partial",
            params=(
                '{"query":null,"topic":null,"paper_id":1,'
                '"max_papers":10,"max_formulas":50,"force":false}'
            ),
            stages_requested=4,
            stages_completed=1,
            results=(
                '{"analyzer":{"papers_analyzed":1},"extractor":{"error":"403",'
                '"time_ms":1200}}'
            ),
            errors='["extractor: 403"]',
        )

        runner = PipelineRunner(db_path)
        plan = runner.build_requeue_plan("run-paper")

        assert plan["strategy"] == "resume_from_current_stage"
        assert plan["stage_names"] == ["extractor", "validator", "codegen"]
        assert plan["stages"] == 3
        assert plan["params"]["paper_id"] == 1
        assert plan["params"]["query"] is None
        assert plan["params"]["requeue_source_failed_stage"] == "extractor"

    def test_rejects_completed_runs(self, db_path):
        _insert_run(
            db_path,
            "run-done",
            "completed",
            params='{"query":"done","paper_id":null}',
            stages_requested=5,
            stages_completed=5,
        )

        runner = PipelineRunner(db_path)
        with pytest.raises(RequeueError, match="already completed successfully"):
            runner.build_requeue_plan("run-done")

    def test_rejects_unscoped_batch_runs(self, db_path):
        _insert_run(
            db_path,
            "run-batch",
            "partial",
            params='{"query":null,"topic":null,"paper_id":null}',
            stages_requested=5,
            stages_completed=2,
        )

        runner = PipelineRunner(db_path)
        with pytest.raises(RequeueError, match="requeued safely"):
            runner.build_requeue_plan("run-batch")

    def test_rejects_paper_requeue_when_paper_is_already_terminal(self, db_path):
        with transaction(db_path) as conn:
            conn.execute(
                "INSERT INTO papers (id, arxiv_id, title, stage) VALUES (?, ?, ?, ?)",
                (7, "2401.00007", "Terminal paper", "codegen"),
            )

        _insert_run(
            db_path,
            "run-terminal-paper",
            "partial",
            params=(
                '{"query":null,"topic":null,"paper_id":7,'
                '"max_papers":10,"max_formulas":50,"force":false}'
            ),
            stages_requested=4,
            stages_completed=3,
            results='{"validator":{"success":true},"codegen":{"error":"stopped"}}',
            errors='["codegen: stopped"]',
        )

        runner = PipelineRunner(db_path)
        with pytest.raises(RequeueError, match="already at terminal stage"):
            runner.build_requeue_plan("run-terminal-paper")

    def test_rejects_running_runs(self, db_path):
        _insert_run(
            db_path,
            "run-active",
            "running",
            params='{"query":"active","paper_id":null}',
        )
        runner = PipelineRunner(db_path)
        with pytest.raises(RequeueError, match="still running and cannot be requeued"):
            runner.build_requeue_plan("run-active")

    def test_requeue_plan_contains_all_audit_metadata(self, db_path):
        _insert_run(
            db_path,
            "run-source",
            "failed",
            params='{"query":"test","paper_id":null,"force":true}',
            results='{"discovery":{"error":"api failure"}}',
        )
        runner = PipelineRunner(db_path)
        plan = runner.build_requeue_plan("run-source")

        params = plan["params"]
        assert params["requeue_of"] == "run-source"
        assert params["requeue_strategy"] == "rerun_query"
        assert params["requeue_source_status"] == "failed"
        assert "requeue_requested_at" in params
        assert params["requeue_source_failed_stage"] == "discovery"
        assert params["force"] is True

    def test_query_runs_remain_rerun_query_and_refuse_resume(self, db_path):
        _insert_run(
            db_path,
            "run-q",
            "failed",
            params='{"query":"test","paper_id":null}',
        )
        runner = PipelineRunner(db_path)

        # auto -> rerun_query
        plan = runner.build_requeue_plan("run-q", strategy="auto")
        assert plan["strategy"] == "rerun_query"

        # manual rerun_query -> ok
        plan = runner.build_requeue_plan("run-q", strategy="rerun_query")
        assert plan["strategy"] == "rerun_query"

        # manual resume_from_current_stage -> error (no paper_id)
        with pytest.raises(RequeueError, match="requires a paper-scoped run"):
            runner.build_requeue_plan("run-q", strategy="resume_from_current_stage")
