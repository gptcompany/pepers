"""Integration tests for Discovery service — real SQLite DB, mock HTTP APIs."""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from unittest.mock import patch

import pytest

from shared.db import transaction
from services.discovery.main import (
    upsert_paper,
    update_paper_s2,
    update_paper_crossref,
    DiscoveryHandler,
)
from shared.server import BaseService


# ---------------------------------------------------------------------------
# TestUpsertPaperDB — real SQLite
# ---------------------------------------------------------------------------


class TestUpsertPaperDB:
    """Integration tests for upsert_paper() with real SQLite."""

    def test_insert_new_paper(self, initialized_db, sample_paper_row):
        paper_id = upsert_paper(str(initialized_db), sample_paper_row)
        assert paper_id is not None
        assert isinstance(paper_id, int)

        with transaction(str(initialized_db)) as conn:
            row = conn.execute(
                "SELECT * FROM papers WHERE id=?", (paper_id,)
            ).fetchone()
        assert row["arxiv_id"] == "2401.00001"
        assert row["title"] == "Kelly Criterion in Portfolio Optimization"
        assert row["stage"] == "discovered"

    def test_upsert_existing_updates_fields(self, initialized_db, sample_paper_row):
        id1 = upsert_paper(str(initialized_db), sample_paper_row)

        updated = dict(sample_paper_row)
        updated["title"] = "Updated Title"
        updated["abstract"] = "Updated abstract"
        id2 = upsert_paper(str(initialized_db), updated)

        assert id1 == id2  # same paper, same id

        with transaction(str(initialized_db)) as conn:
            row = conn.execute(
                "SELECT * FROM papers WHERE id=?", (id1,)
            ).fetchone()
        assert row["title"] == "Updated Title"
        assert row["abstract"] == "Updated abstract"

    def test_upsert_preserves_created_at(self, initialized_db, sample_paper_row):
        upsert_paper(str(initialized_db), sample_paper_row)

        with transaction(str(initialized_db)) as conn:
            row1 = conn.execute(
                "SELECT created_at FROM papers WHERE arxiv_id=?",
                (sample_paper_row["arxiv_id"],),
            ).fetchone()

        # Small delay to ensure updated_at differs
        time.sleep(0.05)
        updated = dict(sample_paper_row)
        updated["title"] = "Changed"
        upsert_paper(str(initialized_db), updated)

        with transaction(str(initialized_db)) as conn:
            row2 = conn.execute(
                "SELECT created_at, updated_at FROM papers WHERE arxiv_id=?",
                (sample_paper_row["arxiv_id"],),
            ).fetchone()

        assert row2["created_at"] == row1["created_at"]

    def test_multiple_papers_unique_ids(self, initialized_db, sample_paper_row):
        id1 = upsert_paper(str(initialized_db), sample_paper_row)

        paper2 = dict(sample_paper_row)
        paper2["arxiv_id"] = "2401.00002"
        id2 = upsert_paper(str(initialized_db), paper2)

        assert id1 != id2

    def test_paper_with_null_optional_fields(self, initialized_db):
        paper = {
            "arxiv_id": "2401.99999",
            "title": "Minimal Paper",
            "abstract": None,
            "authors": None,
            "categories": None,
            "doi": None,
            "pdf_url": None,
            "published_date": None,
            "stage": "discovered",
        }
        paper_id = upsert_paper(str(initialized_db), paper)
        assert paper_id is not None

        with transaction(str(initialized_db)) as conn:
            row = conn.execute(
                "SELECT * FROM papers WHERE id=?", (paper_id,)
            ).fetchone()
        assert row["abstract"] is None
        assert row["doi"] is None


# ---------------------------------------------------------------------------
# TestUpdatePaperS2DB — real SQLite
# ---------------------------------------------------------------------------


class TestUpdatePaperS2DB:
    """Integration tests for update_paper_s2() with real SQLite."""

    def _insert_paper(self, db_path) -> int:
        paper = {
            "arxiv_id": "2401.00001",
            "title": "Test",
            "abstract": "Abstract",
            "authors": '["A"]',
            "categories": '["q-fin.PM"]',
            "doi": None,
            "pdf_url": None,
            "published_date": "2024-01-15",
            "stage": "discovered",
        }
        paper_id = upsert_paper(str(db_path), paper)
        assert paper_id is not None
        return paper_id

    def test_update_s2_fields(self, initialized_db):
        paper_id = self._insert_paper(initialized_db)
        enrichment = {
            "semantic_scholar_id": "abc123",
            "citation_count": 42,
            "reference_count": 15,
            "influential_citation_count": 5,
            "venue": "NIPS",
            "fields_of_study": '["CS", "Math"]',
            "tldr": "Summary text",
            "open_access": 1,
        }
        result = update_paper_s2(str(initialized_db), paper_id, enrichment)
        assert result is True

        with transaction(str(initialized_db)) as conn:
            row = conn.execute(
                "SELECT * FROM papers WHERE id=?", (paper_id,)
            ).fetchone()
        assert row["semantic_scholar_id"] == "abc123"
        assert row["citation_count"] == 42
        assert row["venue"] == "NIPS"
        assert row["open_access"] == 1

    def test_update_with_doi(self, initialized_db):
        paper_id = self._insert_paper(initialized_db)
        enrichment = {
            "semantic_scholar_id": "abc123",
            "citation_count": 10,
            "reference_count": 5,
            "influential_citation_count": 1,
            "venue": "Test",
            "fields_of_study": "[]",
            "tldr": None,
            "open_access": 0,
            "doi": "10.1234/found.by.s2",
        }
        result = update_paper_s2(str(initialized_db), paper_id, enrichment)
        assert result is True

        with transaction(str(initialized_db)) as conn:
            row = conn.execute(
                "SELECT doi FROM papers WHERE id=?", (paper_id,)
            ).fetchone()
        assert row["doi"] == "10.1234/found.by.s2"

    def test_update_nonexistent_paper(self, initialized_db):
        enrichment = {
            "semantic_scholar_id": "xyz",
            "citation_count": 0,
            "reference_count": 0,
            "influential_citation_count": 0,
            "venue": "",
            "fields_of_study": "[]",
            "tldr": None,
            "open_access": 0,
        }
        # Should not raise — UPDATE WHERE id=9999 just affects 0 rows
        result = update_paper_s2(str(initialized_db), 9999, enrichment)
        assert result is True


# ---------------------------------------------------------------------------
# TestUpdatePaperCrossrefDB — real SQLite
# ---------------------------------------------------------------------------


class TestUpdatePaperCrossrefDB:
    """Integration tests for update_paper_crossref() with real SQLite."""

    def _insert_paper(self, db_path) -> int:
        paper = {
            "arxiv_id": "2401.00001",
            "title": "Test",
            "abstract": "Abstract",
            "authors": '["A"]',
            "categories": '["q-fin.PM"]',
            "doi": "10.1234/test",
            "pdf_url": None,
            "published_date": "2024-01-15",
            "stage": "discovered",
        }
        paper_id = upsert_paper(str(db_path), paper)
        assert paper_id is not None
        return paper_id

    def test_store_crossref_json(self, initialized_db):
        paper_id = self._insert_paper(initialized_db)
        cr_data = {
            "DOI": "10.1234/test",
            "title": ["Test Paper"],
            "is-referenced-by-count": 42,
        }
        result = update_paper_crossref(str(initialized_db), paper_id, cr_data)
        assert result is True

        with transaction(str(initialized_db)) as conn:
            row = conn.execute(
                "SELECT crossref_data FROM papers WHERE id=?", (paper_id,)
            ).fetchone()
        stored = json.loads(row["crossref_data"])
        assert stored["DOI"] == "10.1234/test"
        assert stored["is-referenced-by-count"] == 42

    def test_json_round_trip(self, initialized_db):
        paper_id = self._insert_paper(initialized_db)
        original = {"nested": {"list": [1, 2, 3], "null": None, "bool": True}}
        update_paper_crossref(str(initialized_db), paper_id, original)

        with transaction(str(initialized_db)) as conn:
            row = conn.execute(
                "SELECT crossref_data FROM papers WHERE id=?", (paper_id,)
            ).fetchone()
        assert json.loads(row["crossref_data"]) == original


# ---------------------------------------------------------------------------
# TestDiscoveryHandlerIntegration — real server + real DB, mock arXiv/S2/CR
# ---------------------------------------------------------------------------


def _get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class TestDiscoveryHandlerIntegration:
    """Integration tests with real HTTP server and real DB, mocked external APIs."""

    @pytest.fixture(autouse=True)
    def setup_server(self, initialized_db):
        self.db_path = str(initialized_db)
        self.port = _get_free_port()

        service = BaseService(
            "discovery-test", self.port, DiscoveryHandler, db_path=self.db_path
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

    @patch("services.discovery.main.time.sleep")
    @patch("services.discovery.main.enrich_crossref", return_value=None)
    @patch("services.discovery.main.enrich_s2", return_value=None)
    @patch("services.discovery.main.search_arxiv")
    def test_full_pipeline_two_papers(self, mock_search, mock_s2, mock_cr, mock_sleep):
        mock_search.return_value = [
            {
                "arxiv_id": "2401.00001",
                "title": "Paper 1",
                "abstract": "Abstract 1",
                "authors": '["A"]',
                "categories": '["q-fin.PM"]',
                "doi": None,
                "pdf_url": "https://arxiv.org/pdf/2401.00001",
                "published_date": "2024-01-15",
                "stage": "discovered",
            },
            {
                "arxiv_id": "2401.00002",
                "title": "Paper 2",
                "abstract": "Abstract 2",
                "authors": '["B"]',
                "categories": '["stat.ML"]',
                "doi": None,
                "pdf_url": "https://arxiv.org/pdf/2401.00002",
                "published_date": "2024-01-16",
                "stage": "discovered",
            },
        ]

        result = self._post("/process", {"query": "Kelly criterion", "max_results": 10})
        assert result["papers_found"] == 2
        assert result["papers_new"] == 2

        # Verify in DB
        with transaction(self.db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        assert count == 2

    @patch("services.discovery.main.time.sleep")
    @patch("services.discovery.main.enrich_crossref", return_value=None)
    @patch("services.discovery.main.enrich_s2", return_value=None)
    @patch("services.discovery.main.search_arxiv")
    def test_duplicate_run_no_duplicate_rows(self, mock_search, mock_s2, mock_cr, mock_sleep):
        papers = [
            {
                "arxiv_id": "2401.00001",
                "title": "Paper 1",
                "abstract": "A",
                "authors": '["A"]',
                "categories": '["q-fin.PM"]',
                "doi": None,
                "pdf_url": None,
                "published_date": "2024-01-15",
                "stage": "discovered",
            },
        ]
        mock_search.return_value = papers

        r1 = self._post("/process", {"query": "test"})
        assert r1["papers_found"] == 1

        r2 = self._post("/process", {"query": "test"})
        assert r2["papers_found"] == 1

        # Key check: ON CONFLICT dedup means still only 1 row
        with transaction(self.db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        assert count == 1

    @patch("services.discovery.main.search_arxiv", return_value=[])
    def test_empty_search_results(self, mock_search):
        result = self._post("/process", {"query": "nonexistent"})
        assert result["papers_found"] == 0
        assert result["papers_new"] == 0

    @patch("services.discovery.main.time.sleep")
    @patch("services.discovery.main.enrich_crossref", return_value=None)
    @patch("services.discovery.main.enrich_s2", side_effect=Exception("S2 down"))
    @patch("services.discovery.main.search_arxiv")
    def test_s2_failure_partial_enrichment(
        self, mock_search, mock_s2, mock_cr, mock_sleep
    ):
        mock_search.return_value = [
            {
                "arxiv_id": "2401.00001",
                "title": "Paper 1",
                "abstract": "A",
                "authors": '["A"]',
                "categories": '["q-fin.PM"]',
                "doi": None,
                "pdf_url": None,
                "published_date": "2024-01-15",
                "stage": "discovered",
            },
        ]

        result = self._post("/process", {"query": "test"})
        assert result["papers_found"] == 1
        assert result["papers_enriched_s2"] == 0
        assert len(result["errors"]) > 0

    @patch("services.discovery.main.time.sleep")
    @patch("services.discovery.main.enrich_crossref")
    @patch("services.discovery.main.enrich_s2", return_value=None)
    @patch("services.discovery.main.search_arxiv")
    def test_crossref_only_for_journal_doi(
        self, mock_search, mock_s2, mock_cr, mock_sleep
    ):
        mock_search.return_value = [
            {
                "arxiv_id": "2401.00001",
                "title": "Paper without DOI",
                "abstract": "A",
                "authors": '["A"]',
                "categories": '["q-fin.PM"]',
                "doi": None,
                "pdf_url": None,
                "published_date": "2024-01-15",
                "stage": "discovered",
            },
            {
                "arxiv_id": "2401.00002",
                "title": "Paper with DOI",
                "abstract": "B",
                "authors": '["B"]',
                "categories": '["stat.ML"]',
                "doi": "10.1234/journal",
                "pdf_url": None,
                "published_date": "2024-01-16",
                "stage": "discovered",
            },
        ]
        mock_cr.return_value = {"DOI": "10.1234/journal"}

        self._post("/process", {"query": "test"})
        # CrossRef should only be called for paper with DOI
        assert mock_cr.call_count == 1
        mock_cr.assert_called_once_with("10.1234/journal")
