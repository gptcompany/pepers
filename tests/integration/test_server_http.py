"""Integration tests: HTTP server with real database operations."""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

from shared.db import get_connection
from shared.server import BaseHandler, BaseService, route


def _get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.mark.integration
class TestServerWithDB:
    """Test server that reads/writes to a real SQLite database."""

    @pytest.fixture(autouse=True)
    def setup(self, initialized_db):
        self.db_path = str(initialized_db)
        self.port = _get_free_port()

        conn = get_connection(initialized_db)
        conn.execute(
            "INSERT INTO papers (arxiv_id, title, stage) VALUES (?, ?, ?)",
            ("2401.00001", "Test Paper", "discovered"),
        )
        conn.commit()
        conn.close()

        db_path_ref = self.db_path

        class DBHandler(BaseHandler):
            @route("GET", "/papers")
            def handle_list_papers(self):
                conn = get_connection(db_path_ref)
                rows = conn.execute("SELECT arxiv_id, title FROM papers").fetchall()
                conn.close()
                return {"papers": [dict(r) for r in rows]}

            @route("POST", "/papers")
            def handle_add_paper(self, data):
                conn = get_connection(db_path_ref)
                try:
                    conn.execute(
                        "INSERT INTO papers (arxiv_id, title, stage) VALUES (?, ?, ?)",
                        (data["arxiv_id"], data["title"], "discovered"),
                    )
                    conn.commit()
                    return {"success": True, "arxiv_id": data["arxiv_id"]}
                except Exception as e:
                    conn.rollback()
                    self.send_error_json(str(e), "DB_ERROR", 500)
                    return None
                finally:
                    conn.close()

        self.service = BaseService(
            "test-db-svc", self.port, DBHandler, db_path=self.db_path
        )
        self.thread = threading.Thread(target=self.service.run, daemon=True)
        self.thread.start()
        time.sleep(0.3)
        yield
        if self.service.server:
            self.service.server.shutdown()

    def test_list_papers_from_db(self):
        resp = urllib.request.urlopen(f"http://localhost:{self.port}/papers")
        data = json.loads(resp.read())
        assert len(data["papers"]) == 1
        assert data["papers"][0]["arxiv_id"] == "2401.00001"

    def test_add_paper_to_db(self):
        body = json.dumps({"arxiv_id": "2401.00002", "title": "New Paper"}).encode()
        req = urllib.request.Request(
            f"http://localhost:{self.port}/papers",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req)
        data = json.loads(resp.read())
        assert data["success"] is True

        conn = get_connection(self.db_path)
        row = conn.execute(
            "SELECT title FROM papers WHERE arxiv_id=?", ("2401.00002",)
        ).fetchone()
        assert row["title"] == "New Paper"
        conn.close()

    def test_duplicate_paper_error(self):
        body = json.dumps({"arxiv_id": "2401.00001", "title": "Duplicate"}).encode()
        req = urllib.request.Request(
            f"http://localhost:{self.port}/papers",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req)
        assert exc_info.value.code == 500
        data = json.loads(exc_info.value.read())
        assert data["code"] == "DB_ERROR"
