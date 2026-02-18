"""Integration tests for Phase 32 resilience features.

Tests: enhanced /health, startup consistency checks, duplicate prevention.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.request

import pytest

from shared.db import get_connection, init_db
from shared.server import BaseHandler, BaseService, route


# ── Health endpoint tests ──


class _TestHandler(BaseHandler):
    """Minimal handler for health endpoint tests."""

    @route("POST", "/process")
    def handle_process(self, data: dict) -> dict:
        return {"ok": True}


def _get_free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class TestHealthEndpoint:
    """Tests for enhanced /health with DB info."""

    def test_health_returns_db_status(self, tmp_db_path):
        init_db(tmp_db_path)
        port = _get_free_port()
        svc = BaseService("test", port, _TestHandler, str(tmp_db_path))
        t = threading.Thread(target=svc.run, daemon=True)
        t.start()
        time.sleep(0.5)

        try:
            resp = json.loads(
                urllib.request.urlopen(f"http://localhost:{port}/health").read()
            )
            assert resp["status"] == "ok"
            assert resp["db"] == "ok"
            assert resp["schema_version"] == 4
            assert resp["last_request_seconds_ago"] is None  # no requests yet
        finally:
            if svc.server:
                svc.server.shutdown()

    def test_health_degraded_on_bad_db(self, tmp_path):
        port = _get_free_port()
        bad_path = str(tmp_path / "nonexistent" / "dir" / "bad.db")
        # Don't create parent dir — DB open should fail
        svc = BaseService("test", port, _TestHandler, "/dev/null/impossible.db")
        t = threading.Thread(target=svc.run, daemon=True)
        t.start()
        time.sleep(0.5)

        try:
            resp = json.loads(
                urllib.request.urlopen(f"http://localhost:{port}/health").read()
            )
            assert resp["status"] == "degraded"
            assert "error" in resp["db"]
        finally:
            if svc.server:
                svc.server.shutdown()

    def test_health_tracks_last_request(self, tmp_db_path):
        init_db(tmp_db_path)
        port = _get_free_port()
        svc = BaseService("test", port, _TestHandler, str(tmp_db_path))
        t = threading.Thread(target=svc.run, daemon=True)
        t.start()
        time.sleep(0.5)

        try:
            # Make a request to /process
            req = urllib.request.Request(
                f"http://localhost:{port}/process",
                data=json.dumps({"x": 1}).encode(),
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req)

            # Now check /health — should show last_request_seconds_ago
            resp = json.loads(
                urllib.request.urlopen(f"http://localhost:{port}/health").read()
            )
            assert resp["last_request_seconds_ago"] is not None
            assert resp["last_request_seconds_ago"] < 5.0
        finally:
            if svc.server:
                svc.server.shutdown()


# ── Consistency check tests ──


class TestExtractorConsistency:
    """Tests for extractor startup consistency check."""

    def test_detects_empty_extraction(self, tmp_db_path, caplog):
        init_db(tmp_db_path)
        conn = get_connection(tmp_db_path)
        conn.execute(
            "INSERT INTO papers (arxiv_id, title, stage) VALUES ('test', 'T', 'extracted')"
        )
        conn.commit()
        conn.close()

        from services.extractor.main import _check_consistency

        with caplog.at_level(logging.WARNING):
            _check_consistency(str(tmp_db_path))

        assert "stage 'extracted' with 0 formulas" in caplog.text

    def test_no_warning_on_clean_db(self, tmp_db_path, caplog):
        init_db(tmp_db_path)

        from services.extractor.main import _check_consistency

        with caplog.at_level(logging.WARNING):
            _check_consistency(str(tmp_db_path))

        assert "Consistency" not in caplog.text


class TestValidatorConsistency:
    """Tests for validator startup consistency check."""

    def test_detects_partial_validations(self, tmp_db_path, caplog):
        init_db(tmp_db_path)
        conn = get_connection(tmp_db_path)
        conn.execute(
            "INSERT INTO papers (arxiv_id, title, stage) VALUES ('test', 'T', 'extracted')"
        )
        conn.execute(
            "INSERT INTO formulas (paper_id, latex, latex_hash, stage) "
            "VALUES (1, 'x^2', 'abc', 'extracted')"
        )
        conn.execute(
            "INSERT INTO validations (formula_id, engine, is_valid, result, time_ms) "
            "VALUES (1, 'matlab', 1, 'x^2', 100)"
        )
        conn.commit()
        conn.close()

        from services.validator.main import _check_consistency

        with caplog.at_level(logging.WARNING):
            _check_consistency(str(tmp_db_path))

        assert "partial validations" in caplog.text


class TestCodegenConsistency:
    """Tests for codegen startup consistency check."""

    def test_detects_partial_codegen(self, tmp_db_path, caplog):
        init_db(tmp_db_path)
        conn = get_connection(tmp_db_path)
        conn.execute(
            "INSERT INTO papers (arxiv_id, title, stage) VALUES ('test', 'T', 'validated')"
        )
        conn.execute(
            "INSERT INTO formulas (paper_id, latex, latex_hash, stage) "
            "VALUES (1, 'x^2', 'abc', 'validated')"
        )
        conn.execute(
            "INSERT INTO generated_code (formula_id, language, code) "
            "VALUES (1, 'python', 'x**2')"
        )
        conn.commit()
        conn.close()

        from services.codegen.main import _check_consistency

        with caplog.at_level(logging.WARNING):
            _check_consistency(str(tmp_db_path))

        assert "partial codegen" in caplog.text


class TestConsistencyGeneral:
    """General consistency check tests."""

    def test_does_not_crash_on_empty_db(self, tmp_db_path):
        """Consistency checks should not crash on empty database."""
        init_db(tmp_db_path)

        from services.extractor.main import _check_consistency as ext_check
        from services.validator.main import _check_consistency as val_check
        from services.codegen.main import _check_consistency as cod_check

        ext_check(str(tmp_db_path))
        val_check(str(tmp_db_path))
        cod_check(str(tmp_db_path))


# ── Duplicate prevention test ──


class TestDuplicatePrevention:
    """Test UNIQUE constraint on formulas."""

    def test_insert_or_ignore_for_idempotent_extraction(self, tmp_db_path):
        """INSERT OR IGNORE should silently skip duplicate (paper_id, latex_hash)."""
        init_db(tmp_db_path)
        conn = get_connection(tmp_db_path)
        conn.execute(
            "INSERT INTO papers (arxiv_id, title, stage) VALUES ('test', 'T', 'discovered')"
        )
        conn.execute(
            "INSERT INTO formulas (paper_id, latex, latex_hash, stage) "
            "VALUES (1, 'x^2', 'abc', 'extracted')"
        )
        # INSERT OR IGNORE should not raise
        conn.execute(
            "INSERT OR IGNORE INTO formulas (paper_id, latex, latex_hash, stage) "
            "VALUES (1, 'x^2', 'abc', 'extracted')"
        )
        conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM formulas").fetchone()[0]
        conn.close()
        assert count == 1  # duplicate was ignored
