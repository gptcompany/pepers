"""Integration tests for custom notations API endpoints on the orchestrator."""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

from shared.db import get_connection, init_db


def _get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _request(port: int, method: str, path: str, data: dict | None = None):
    """Send HTTP request and return (status, json_body)."""
    url = f"http://localhost:{port}{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method)
    if body:
        req.add_header("Content-Type", "application/json")
    try:
        resp = urllib.request.urlopen(req)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


@pytest.mark.integration
class TestNotationsAPI:
    """Test orchestrator /notations endpoints."""

    @pytest.fixture(autouse=True)
    def setup(self, initialized_db):
        """Start an orchestrator service with a temp database."""
        from services.orchestrator.main import OrchestratorHandler
        from shared.server import BaseService

        self.db_path = str(initialized_db)
        self.port = _get_free_port()

        self.service = BaseService(
            "test-notations", self.port, OrchestratorHandler, db_path=self.db_path
        )
        self.thread = threading.Thread(target=self.service.run, daemon=True)
        self.thread.start()
        time.sleep(0.3)
        yield
        if self.service.server:
            self.service.server.shutdown()

    # -- POST /notations (add/upsert) --

    def test_add_notation(self):
        status, body = _request(self.port, "POST", "/notations", {
            "name": "Expect",
            "body": r"\mathbb{E}\left[#1\right]",
            "nargs": 1,
            "description": "Expected value",
        })
        assert status == 200
        assert body["success"] is True
        assert body["name"] == "Expect"
        assert body["action"] == "upserted"

    def test_add_notation_missing_name(self):
        status, body = _request(self.port, "POST", "/notations", {
            "name": "",
            "body": r"\mathbb{R}",
        })
        assert status == 400
        assert "name and body are required" in body.get("error", "")

    def test_add_notation_missing_body(self):
        status, body = _request(self.port, "POST", "/notations", {
            "name": "R",
            "body": "",
        })
        assert status == 400

    def test_add_notation_nargs_out_of_range(self):
        status, body = _request(self.port, "POST", "/notations", {
            "name": "Bad",
            "body": "x",
            "nargs": 10,
        })
        assert status == 400
        assert "nargs must be 0-9" in body.get("error", "")

    def test_add_notation_negative_nargs(self):
        status, body = _request(self.port, "POST", "/notations", {
            "name": "Bad",
            "body": "x",
            "nargs": -1,
        })
        assert status == 400

    def test_upsert_updates_existing(self):
        """Second POST with same name updates the record."""
        _request(self.port, "POST", "/notations", {
            "name": "Var",
            "body": "old_body",
            "nargs": 0,
        })
        _request(self.port, "POST", "/notations", {
            "name": "Var",
            "body": "new_body",
            "nargs": 1,
        })
        status, body = _request(self.port, "GET", "/notations")
        assert status == 200
        var = [n for n in body if n["name"] == "Var"]
        assert len(var) == 1
        assert var[0]["body"] == "new_body"
        assert var[0]["nargs"] == 1

    # -- GET /notations (list) --

    def test_list_empty(self):
        status, body = _request(self.port, "GET", "/notations")
        assert status == 200
        assert body == []

    def test_list_after_add(self):
        _request(self.port, "POST", "/notations", {
            "name": "Alpha",
            "body": r"\alpha",
        })
        _request(self.port, "POST", "/notations", {
            "name": "Beta",
            "body": r"\beta",
        })
        status, body = _request(self.port, "GET", "/notations")
        assert status == 200
        assert len(body) == 2
        names = [n["name"] for n in body]
        assert names == ["Alpha", "Beta"]  # ordered by name

    # -- POST /notations/delete --

    def test_delete_notation(self):
        _request(self.port, "POST", "/notations", {
            "name": "ToDelete",
            "body": "x",
        })
        status, body = _request(self.port, "POST", "/notations/delete", {
            "name": "ToDelete",
        })
        assert status == 200
        assert body["success"] is True
        assert body["action"] == "deleted"

        # Verify gone
        _, items = _request(self.port, "GET", "/notations")
        assert all(n["name"] != "ToDelete" for n in items)

    def test_delete_nonexistent(self):
        status, body = _request(self.port, "POST", "/notations/delete", {
            "name": "Ghost",
        })
        assert status == 404

    def test_delete_missing_name(self):
        status, body = _request(self.port, "POST", "/notations/delete", {
            "name": "",
        })
        assert status == 400

    # -- Schema migration check --

    def test_schema_v6_applied(self):
        """Verify custom_notations table exists after init_db."""
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='custom_notations'"
            ).fetchone()
            assert row is not None
            ver = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
            assert ver >= 6
        finally:
            conn.close()
