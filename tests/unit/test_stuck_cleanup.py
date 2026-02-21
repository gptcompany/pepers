"""Unit tests for RES-01: Stuck pipeline run cleanup at orchestrator startup."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from shared.db import init_db, transaction
from services.orchestrator.pipeline import PipelineRunner


@pytest.fixture
def db_path():
    """Create a temporary database with pipeline_runs table."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = str(Path(tmpdir) / "test.db")
        init_db(path)
        yield path


def _insert_run(db_path: str, run_id: str, status: str, started_minutes_ago: int = 0) -> None:
    """Insert a pipeline run with a specific started_at offset."""
    with transaction(db_path) as conn:
        conn.execute(
            "INSERT INTO pipeline_runs (run_id, status, params, stages_requested, started_at) "
            "VALUES (?, ?, '{}', 1, datetime('now', ?))",
            (run_id, status, f"-{started_minutes_ago} minutes"),
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
