"""Shared E2E test fixtures — real HTTP servers, real DB, no mocks."""

from __future__ import annotations

import socket
import threading
import time

import pytest

from shared.db import init_db, transaction
from shared.server import BaseService
from services.orchestrator.main import OrchestratorHandler
from services.orchestrator.pipeline import PipelineRunner


def _get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture
def e2e_orchestrator(tmp_path):
    """Start a real orchestrator server with a temp DB.

    Each test gets an isolated DB and server instance.
    Fixture scope: function (default) — full isolation.
    """
    db_path = tmp_path / "e2e_orchestrator.db"
    init_db(db_path)

    # Seed with test data
    with transaction(str(db_path)) as conn:
        conn.execute(
            "INSERT INTO papers (arxiv_id, title, stage) VALUES (?, ?, ?)",
            ("2401.00001", "Kelly Criterion E2E Paper", "discovered"),
        )
        conn.execute(
            "INSERT INTO papers (arxiv_id, title, stage) VALUES (?, ?, ?)",
            ("2401.00002", "Optimal Betting E2E Paper", "analyzed"),
        )

    port = _get_free_port()
    runner = PipelineRunner(str(db_path))
    OrchestratorHandler.runner = runner

    service = BaseService(
        "orchestrator", port, OrchestratorHandler, str(db_path)
    )
    thread = threading.Thread(target=service.run, daemon=True)
    thread.start()
    time.sleep(0.3)

    yield {"port": port, "db_path": str(db_path), "service": service}

    if service.server:
        service.server.shutdown()
    OrchestratorHandler.runner = None
    OrchestratorHandler._routes = None
