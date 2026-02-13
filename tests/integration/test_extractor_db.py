"""Integration tests for Extractor service — real SQLite DB, mock external HTTP."""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import pytest

from shared.db import transaction
from shared.models import Formula
from services.extractor.main import (
    ExtractorHandler,
    _mark_failed,
    _query_papers,
    _store_results,
)
from services.discovery.main import upsert_paper
from shared.server import BaseService


# ---------------------------------------------------------------------------
# TestQueryPapers
# ---------------------------------------------------------------------------


class TestQueryPapers:
    """Tests for _query_papers() with real SQLite."""

    def test_query_analyzed_papers(self, analyzed_paper_db):
        papers = _query_papers(str(analyzed_paper_db), None, 10, False)
        assert len(papers) == 1
        assert papers[0]["stage"] == "analyzed"

    def test_query_specific_paper_id(self, analyzed_paper_db):
        papers = _query_papers(str(analyzed_paper_db), 1, 10, False)
        assert len(papers) == 1
        assert papers[0]["id"] == 1

    def test_force_includes_extracted_and_failed(self, analyzed_paper_db):
        db = str(analyzed_paper_db)
        # Change paper stage to extracted
        with transaction(db) as conn:
            conn.execute("UPDATE papers SET stage='extracted' WHERE id=1")

        # Without force: no results
        papers = _query_papers(db, None, 10, False)
        assert len(papers) == 0

        # With force + paper_id: found
        papers = _query_papers(db, 1, 10, True)
        assert len(papers) == 1

    def test_respects_limit(self, analyzed_paper_db):
        db = str(analyzed_paper_db)
        # Add more analyzed papers
        for i in range(5):
            upsert_paper(db, {
                "arxiv_id": f"2401.0000{i+2}",
                "title": f"Paper {i+2}",
                "abstract": "Abstract",
                "authors": '["A"]',
                "categories": '["q-fin.PM"]',
                "doi": None,
                "pdf_url": None,
                "published_date": "2024-01-15",
                "stage": "analyzed",
            })

        papers = _query_papers(db, None, 3, False)
        assert len(papers) == 3


# ---------------------------------------------------------------------------
# TestStoreResults
# ---------------------------------------------------------------------------


class TestStoreResults:
    """Tests for _store_results() with real SQLite."""

    def test_inserts_formulas(self, analyzed_paper_db):
        db = str(analyzed_paper_db)
        formulas = [
            Formula(
                paper_id=1,
                latex=r"\frac{p}{q}",
                formula_type="display",
                context="The Kelly formula",
            ),
            Formula(
                paper_id=1,
                latex=r"E = mc^2",
                formula_type="display",
                context="Energy equation",
            ),
        ]

        _store_results(db, 1, formulas)

        with transaction(db) as conn:
            rows = conn.execute("SELECT * FROM formulas WHERE paper_id=1").fetchall()
        assert len(rows) == 2

    def test_updates_paper_stage(self, analyzed_paper_db):
        db = str(analyzed_paper_db)
        _store_results(db, 1, [])

        with transaction(db) as conn:
            row = conn.execute("SELECT stage FROM papers WHERE id=1").fetchone()
        assert row["stage"] == "extracted"

    def test_deduplicates_by_latex_hash(self, analyzed_paper_db):
        db = str(analyzed_paper_db)
        f = Formula(paper_id=1, latex=r"\alpha + \beta", formula_type="inline")

        _store_results(db, 1, [f, f])

        with transaction(db) as conn:
            rows = conn.execute("SELECT * FROM formulas WHERE paper_id=1").fetchall()
        # Same hash → only one inserted
        assert len(rows) == 1

    def test_empty_formulas_still_updates_stage(self, analyzed_paper_db):
        db = str(analyzed_paper_db)
        _store_results(db, 1, [])

        with transaction(db) as conn:
            row = conn.execute("SELECT stage FROM papers WHERE id=1").fetchone()
        assert row["stage"] == "extracted"

        with transaction(db) as conn:
            count = conn.execute("SELECT COUNT(*) FROM formulas WHERE paper_id=1").fetchone()[0]
        assert count == 0


# ---------------------------------------------------------------------------
# TestMarkFailed
# ---------------------------------------------------------------------------


class TestMarkFailed:
    """Tests for _mark_failed() with real SQLite."""

    def test_marks_paper_failed(self, analyzed_paper_db):
        db = str(analyzed_paper_db)
        _mark_failed(db, 1, "pdf_download: 404")

        with transaction(db) as conn:
            row = conn.execute("SELECT stage, error FROM papers WHERE id=1").fetchone()
        assert row["stage"] == "failed"
        assert "pdf_download: 404" in row["error"]

    def test_error_prefix(self, analyzed_paper_db):
        db = str(analyzed_paper_db)
        _mark_failed(db, 1, "some error")

        with transaction(db) as conn:
            row = conn.execute("SELECT error FROM papers WHERE id=1").fetchone()
        assert row["error"].startswith("extractor: ")


# ---------------------------------------------------------------------------
# TestExtractorHandlerIntegration — real server + real DB, mock external
# ---------------------------------------------------------------------------


def _get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class TestExtractorHandlerIntegration:
    """Integration tests with real HTTP server and real DB, mocked externals."""

    @pytest.fixture(autouse=True)
    def setup_server(self, analyzed_paper_db, tmp_path):
        self.db_path = str(analyzed_paper_db)
        self.port = _get_free_port()
        self.pdf_dir = str(tmp_path / "pdfs")

        ExtractorHandler.max_papers_default = 10
        ExtractorHandler.pdf_dir = self.pdf_dir
        ExtractorHandler.rag_url = "http://localhost:8767"
        ExtractorHandler.download_delay = 0.0  # No delay in tests

        service = BaseService(
            "extractor-test", self.port, ExtractorHandler, db_path=self.db_path
        )
        self.thread = threading.Thread(target=service.run, daemon=True)
        self.thread.start()
        time.sleep(0.3)
        self.service = service
        yield
        if service.server:
            service.server.shutdown()

    def _post(self, path, data):
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            f"http://localhost:{self.port}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req)
        return json.loads(resp.read())

    def _post_error(self, path, data):
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            f"http://localhost:{self.port}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req)
        return exc_info.value.code, json.loads(exc_info.value.read())

    def test_process_no_papers(self):
        # Change paper stage so nothing matches
        with transaction(self.db_path) as conn:
            conn.execute("UPDATE papers SET stage='discovered' WHERE id=1")

        result = self._post("/process", {})
        assert result["papers_processed"] == 0
        assert result["formulas_extracted"] == 0

    @patch("services.extractor.main.rag_client.process_paper")
    @patch("services.extractor.main.pdf.download_pdf")
    @patch("services.extractor.main.rag_client.check_service")
    def test_process_single_paper_full_flow(
        self, mock_check, mock_download, mock_process
    ):
        mock_check.return_value = {"status": "ok"}
        mock_download.return_value = Path("/tmp/fake.pdf")
        mock_process.return_value = (
            "# Paper\nThe formula is "
            r"\begin{equation} f^* = \frac{p}{a} - \frac{q}{b} \end{equation}."
        )

        result = self._post("/process", {})
        assert result["papers_processed"] == 1
        assert result["formulas_extracted"] >= 1

        # Verify DB state
        with transaction(self.db_path) as conn:
            row = conn.execute("SELECT stage FROM papers WHERE id=1").fetchone()
        assert row["stage"] == "extracted"

    @patch("services.extractor.main.rag_client.check_service")
    def test_rag_unavailable_returns_503(self, mock_check):
        mock_check.side_effect = RuntimeError("RAGAnything circuit breaker is open")

        code, body = self._post_error("/process", {})
        assert code == 503
        assert "circuit breaker" in body.get("error", "")
