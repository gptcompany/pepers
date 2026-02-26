"""Unit tests for services/discovery/main.py — all external calls mocked."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import requests

from services.discovery.main import (
    DEFAULT_MAX_RESULTS,
    DiscoveryHandler,
    extract_arxiv_id,
    search_arxiv,
    enrich_s2,
    enrich_crossref,
    upsert_paper,
    update_paper_s2,
    update_paper_crossref,
)


# ---------------------------------------------------------------------------
# TestDiscoveryHandler
# ---------------------------------------------------------------------------


class TestDiscoveryHandler:
    """Tests for DiscoveryHandler full flow."""

    def _make_handler(self, db_path):
        handler = DiscoveryHandler.__new__(DiscoveryHandler)
        handler.db_path = db_path
        handler.send_error_json = MagicMock()
        return handler

    @patch("services.discovery.main.search_arxiv")
    @patch("services.discovery.main.upsert_paper")
    @patch("services.discovery.main.enrich_s2")
    @patch("services.discovery.main.enrich_crossref")
    @patch("services.discovery.main.time.sleep")
    def test_handle_process_arxiv_full_flow(self, mock_sleep, mock_cr, mock_s2, mock_upsert, mock_search, initialized_db):
        db_path = str(initialized_db)
        handler = self._make_handler(db_path)
        
        mock_search.return_value = [{"arxiv_id": "2401.00001", "title": "T", "doi": "10.1/j"}]
        mock_upsert.return_value = 1
        mock_s2.return_value = {"semantic_scholar_id": "s2_1", "citation_count": 10}
        mock_cr.return_value = {"DOI": "10.1/j", "title": ["T"]}
        
        # Mock created_at == updated_at to count as new
        from shared.db import transaction
        with transaction(db_path) as conn:
            conn.execute("INSERT INTO papers (id, arxiv_id, title, stage, created_at, updated_at) VALUES (1, '2401.00001', 'T', 'discovered', '2024-01-01', '2024-01-01')")

        resp = handler.handle_process({"query": "test", "sources": ["arxiv"]})
        
        assert resp["papers_found"] == 1
        assert resp["papers_new"] == 1
        assert resp["papers_enriched_s2"] == 1
        assert resp["papers_enriched_cr"] == 1
        assert len(resp["errors"]) == 0

    @patch("services.discovery.main.search_arxiv", side_effect=Exception("Arxiv Down"))
    def test_handle_process_arxiv_error(self, mock_search, initialized_db):
        handler = self._make_handler(str(initialized_db))
        resp = handler.handle_process({"query": "test", "sources": ["arxiv"]})
        assert "Arxiv Down" in resp["errors"][0]

    @patch("services.discovery.openalex.search_openalex")
    @patch("services.discovery.openalex.upsert_openalex_paper")
    def test_handle_process_openalex_flow(self, mock_upsert, mock_search, initialized_db):
        db_path = str(initialized_db)
        handler = self._make_handler(db_path)
        
        mock_search.return_value = [{"openalex_id": "W123", "title": "T"}]
        mock_upsert.return_value = 1
        
        # Mock already exists (updated_at > created_at)
        from shared.db import transaction
        with transaction(db_path) as conn:
            conn.execute("INSERT INTO papers (id, arxiv_id, openalex_id, title, stage, created_at, updated_at) VALUES (1, 'arxiv_1', 'W123', 'T', 'discovered', '2024-01-01', '2024-01-02')")

        resp = handler.handle_process({"query": "test", "sources": ["openalex"]})
        
        assert resp["papers_found"] == 1
        assert resp["papers_new"] == 0
        assert len(resp["errors"]) == 0

    def test_handle_process_invalid_source(self, initialized_db):
        handler = self._make_handler(str(initialized_db))
        resp = handler.handle_process({"query": "test", "sources": ["invalid"]})
        assert resp is None
        handler.send_error_json.assert_called_once()


# ---------------------------------------------------------------------------
# TestExtractArxivId
# ---------------------------------------------------------------------------


class TestExtractArxivId:
    """Tests for extract_arxiv_id()."""

    def test_versioned_id(self):
        r = MagicMock()
        r.entry_id = "http://arxiv.org/abs/2107.05580v2"
        assert extract_arxiv_id(r) == "2107.05580"

    def test_unversioned_id(self):
        r = MagicMock()
        r.entry_id = "http://arxiv.org/abs/2107.05580"
        assert extract_arxiv_id(r) == "2107.05580"

    def test_old_style_id_with_version(self):
        # rsplit("/", 1) takes last segment only, so "cs/0112017v1" -> "0112017v1" -> "0112017"
        r = MagicMock()
        r.entry_id = "http://arxiv.org/abs/cs/0112017v1"
        assert extract_arxiv_id(r) == "0112017"

    def test_multi_digit_version(self):
        r = MagicMock()
        r.entry_id = "http://arxiv.org/abs/2401.12345v12"
        assert extract_arxiv_id(r) == "2401.12345"

    def test_no_version_suffix_unchanged(self):
        r = MagicMock()
        r.entry_id = "http://arxiv.org/abs/2401.99999"
        assert extract_arxiv_id(r) == "2401.99999"


# ---------------------------------------------------------------------------
# TestSearchArxiv
# ---------------------------------------------------------------------------


class TestSearchArxiv:
    """Tests for search_arxiv() — mock arxiv.Client and arxiv.Search."""

    def _make_result(self, entry_id, title="Test", doi=None, categories=None):
        """Helper to create a mock arxiv.Result."""
        from datetime import datetime, timezone

        r = MagicMock()
        r.entry_id = entry_id
        r.title = title
        r.summary = "Abstract text"
        r.doi = doi
        r.pdf_url = f"https://arxiv.org/pdf/{entry_id.rsplit('/', 1)[-1]}"
        r.published = datetime(2024, 1, 15, tzinfo=timezone.utc)
        r.categories = set(categories or ["q-fin.PM"])
        a = MagicMock()
        a.name = "Author One"
        r.authors = [a]
        return r

    @patch("services.discovery.main.arxiv.Client")
    @patch("services.discovery.main.arxiv.Search")
    def test_returns_paper_dicts(self, mock_search_cls, mock_client_cls):
        result = self._make_result(
            "http://arxiv.org/abs/2401.00001v1",
            doi="10.1234/journal.2024",
        )
        mock_client = MagicMock()
        mock_client.results.return_value = [result]
        mock_client_cls.return_value = mock_client

        papers = search_arxiv("Kelly criterion", 10)
        assert len(papers) == 1
        p = papers[0]
        assert p["arxiv_id"] == "2401.00001"
        assert p["doi"] == "10.1234/journal.2024"
        assert p["stage"] == "discovered"
        assert json.loads(p["authors"]) == ["Author One"]

    @patch("services.discovery.main.arxiv.Client")
    @patch("services.discovery.main.arxiv.Search")
    def test_filters_datacite_doi(self, mock_search_cls, mock_client_cls):
        result = self._make_result(
            "http://arxiv.org/abs/2401.00001v1",
            doi="10.48550/arXiv.2401.00001",
        )
        mock_client = MagicMock()
        mock_client.results.return_value = [result]
        mock_client_cls.return_value = mock_client

        papers = search_arxiv("test", 10)
        assert papers[0]["doi"] is None

    @patch("services.discovery.main.arxiv.Client")
    @patch("services.discovery.main.arxiv.Search")
    def test_keeps_journal_doi(self, mock_search_cls, mock_client_cls):
        result = self._make_result(
            "http://arxiv.org/abs/2401.00001v1",
            doi="10.1016/j.jfineco.2024.01.001",
        )
        mock_client = MagicMock()
        mock_client.results.return_value = [result]
        mock_client_cls.return_value = mock_client

        papers = search_arxiv("test", 10)
        assert papers[0]["doi"] == "10.1016/j.jfineco.2024.01.001"

    @patch("services.discovery.main.arxiv.Client")
    @patch("services.discovery.main.arxiv.Search")
    def test_empty_results(self, mock_search_cls, mock_client_cls):
        mock_client = MagicMock()
        mock_client.results.return_value = []
        mock_client_cls.return_value = mock_client

        papers = search_arxiv("nonexistent query", 10)
        assert papers == []

    @patch("services.discovery.main.arxiv.Client")
    @patch("services.discovery.main.arxiv.Search")
    def test_categories_serialized_as_json(self, mock_search_cls, mock_client_cls):
        result = self._make_result(
            "http://arxiv.org/abs/2401.00001v1",
            categories=["q-fin.PM", "stat.ML"],
        )
        mock_client = MagicMock()
        mock_client.results.return_value = [result]
        mock_client_cls.return_value = mock_client

        papers = search_arxiv("test", 10)
        cats = json.loads(papers[0]["categories"])
        assert isinstance(cats, list)
        assert len(cats) == 2

    @patch("services.discovery.main.arxiv.Client")
    @patch("services.discovery.main.arxiv.Search")
    def test_published_date_iso_format(self, mock_search_cls, mock_client_cls):
        result = self._make_result("http://arxiv.org/abs/2401.00001v1")
        mock_client = MagicMock()
        mock_client.results.return_value = [result]
        mock_client_cls.return_value = mock_client

        papers = search_arxiv("test", 10)
        assert "2024-01-15" in papers[0]["published_date"]


# ---------------------------------------------------------------------------
# TestEnrichS2
# ---------------------------------------------------------------------------


class TestEnrichS2:
    """Tests for enrich_s2() — mock requests.get."""

    @patch("services.discovery.main.requests.get")
    def test_200_success_full_data(self, mock_get, sample_s2_response):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = sample_s2_response
        mock_get.return_value = mock_resp

        result = enrich_s2("2401.00001")
        assert result is not None
        assert result["semantic_scholar_id"] == "abc123def456"
        assert result["citation_count"] == 42
        assert result["reference_count"] == 15
        assert result["influential_citation_count"] == 5
        assert result["venue"] == "Journal of Finance"
        assert result["open_access"] == 1
        assert result["tldr"] == "This paper studies the Kelly criterion."
        fos = json.loads(result["fields_of_study"])
        assert "Economics" in fos
        assert "Mathematics" in fos

    @patch("services.discovery.main.requests.get")
    def test_200_with_missing_optional_fields(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "paperId": "xyz789",
            "externalIds": {},
        }
        mock_get.return_value = mock_resp

        result = enrich_s2("2401.00001")
        assert result is not None
        assert result["semantic_scholar_id"] == "xyz789"
        assert result["citation_count"] == 0
        assert result["tldr"] is None
        assert result["open_access"] == 0
        assert json.loads(result["fields_of_study"]) == []

    @patch("services.discovery.main.requests.get")
    def test_200_with_journal_doi(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "paperId": "xyz",
            "externalIds": {"DOI": "10.1234/journal.doi"},
        }
        mock_get.return_value = mock_resp

        result = enrich_s2("2401.00001")
        assert result is not None
        assert result["doi"] == "10.1234/journal.doi"

    @patch("services.discovery.main.requests.get")
    def test_200_with_datacite_doi_excluded(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "paperId": "xyz",
            "externalIds": {"DOI": "10.48550/arXiv.2401.00001"},
        }
        mock_get.return_value = mock_resp

        result = enrich_s2("2401.00001")
        assert result is not None
        assert "doi" not in result

    @patch("services.discovery.main.requests.get")
    def test_404_returns_none(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp

        result = enrich_s2("nonexistent")
        assert result is None

    @patch("services.discovery.main.time.sleep")
    @patch("services.discovery.main.requests.get")
    def test_429_retry_then_success(self, mock_get, mock_sleep):
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.headers = {"Retry-After": "2"}

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {"paperId": "retried", "externalIds": {}}
        mock_get.side_effect = [resp_429, resp_200]

        result = enrich_s2("2401.00001")
        assert result is not None
        assert result["semantic_scholar_id"] == "retried"
        mock_sleep.assert_called_once_with(2)

    @patch("services.discovery.main.time.sleep")
    @patch("services.discovery.main.requests.get")
    def test_429_both_attempts_returns_none(self, mock_get, mock_sleep):
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.headers = {"Retry-After": "1"}

        resp_500 = MagicMock()
        resp_500.status_code = 500
        mock_get.side_effect = [resp_429, resp_500]

        result = enrich_s2("2401.00001")
        assert result is None

    @patch("services.discovery.main.requests.get")
    def test_request_exception_returns_none(self, mock_get):
        mock_get.side_effect = requests.RequestException("Connection error")
        result = enrich_s2("2401.00001")
        assert result is None


# ---------------------------------------------------------------------------
# TestEnrichCrossref
# ---------------------------------------------------------------------------


class TestEnrichCrossref:
    """Tests for enrich_crossref() — mock requests.get."""

    @patch("services.discovery.main.requests.get")
    def test_200_success(self, mock_get, sample_crossref_response):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = sample_crossref_response
        mock_get.return_value = mock_resp

        result = enrich_crossref("10.1234/test.2024.001")
        assert result is not None
        assert result["DOI"] == "10.1234/test.2024.001"
        assert result["type"] == "journal-article"

    @patch("services.discovery.main.requests.get")
    def test_404_returns_none(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp

        result = enrich_crossref("10.9999/nonexistent")
        assert result is None

    @patch("services.discovery.main.time.sleep")
    @patch("services.discovery.main.requests.get")
    def test_429_retry_then_success(self, mock_get, mock_sleep):
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.headers = {"Retry-After": "3"}

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {"message": {"DOI": "10.1234/ok"}}
        mock_get.side_effect = [resp_429, resp_200]

        result = enrich_crossref("10.1234/ok")
        assert result is not None
        assert result["DOI"] == "10.1234/ok"
        mock_sleep.assert_called_once_with(3)

    @patch("services.discovery.main.time.sleep")
    @patch("services.discovery.main.requests.get")
    def test_429_retry_still_fails(self, mock_get, mock_sleep):
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.headers = {"Retry-After": "1"}

        resp_500 = MagicMock()
        resp_500.status_code = 500
        mock_get.side_effect = [resp_429, resp_500]

        result = enrich_crossref("10.1234/fail")
        assert result is None

    @patch("services.discovery.main.requests.get")
    def test_request_exception_returns_none(self, mock_get):
        mock_get.side_effect = requests.RequestException("Timeout")
        result = enrich_crossref("10.1234/fail")
        assert result is None

    @patch("services.discovery.main.requests.get")
    def test_extracts_message_from_response(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "ok",
            "message": {"key": "value"},
        }
        mock_get.return_value = mock_resp

        result = enrich_crossref("10.1234/test")
        assert result == {"key": "value"}


# ---------------------------------------------------------------------------
# TestUpsertPaper
# ---------------------------------------------------------------------------


class TestUpsertPaper:
    """Tests for upsert_paper() — mock transaction."""

    @patch("services.discovery.main.transaction")
    def test_new_paper_returns_id(self, mock_txn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1,)
        mock_conn.execute.return_value = mock_cursor
        mock_txn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_txn.return_value.__exit__ = MagicMock(return_value=False)

        paper = {
            "arxiv_id": "2401.00001",
            "title": "Test Paper",
            "abstract": "Abstract",
            "authors": '["A"]',
            "categories": '["q-fin.PM"]',
            "doi": None,
            "pdf_url": "https://arxiv.org/pdf/2401.00001",
            "published_date": "2024-01-15",
            "stage": "discovered",
        }
        result = upsert_paper("/tmp/test.db", paper)
        assert result == 1
        mock_conn.execute.assert_called_once()

    @patch("services.discovery.main.transaction")
    def test_existing_paper_returns_updated_id(self, mock_txn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (5,)
        mock_conn.execute.return_value = mock_cursor
        mock_txn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_txn.return_value.__exit__ = MagicMock(return_value=False)

        paper = {
            "arxiv_id": "2401.00001",
            "title": "Updated Title",
            "abstract": "Updated abstract",
            "authors": '["B"]',
            "categories": '["stat.ML"]',
            "doi": "10.1234/new",
            "pdf_url": "https://arxiv.org/pdf/2401.00001",
            "published_date": "2024-01-15",
            "stage": "discovered",
        }
        result = upsert_paper("/tmp/test.db", paper)
        assert result == 5

    @patch("services.discovery.main.transaction")
    def test_missing_optional_fields_uses_none(self, mock_txn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1,)
        mock_conn.execute.return_value = mock_cursor
        mock_txn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_txn.return_value.__exit__ = MagicMock(return_value=False)

        paper = {"arxiv_id": "2401.00001", "title": "Minimal", "stage": "discovered"}
        result = upsert_paper("/tmp/test.db", paper)
        assert result == 1
        # Verify None values passed for missing keys
        args = mock_conn.execute.call_args[0][1]
        assert args[2] is None  # abstract
        assert args[5] is None  # doi

    @patch("services.discovery.main.transaction")
    def test_db_error_returns_none(self, mock_txn):
        mock_txn.return_value.__enter__ = MagicMock(
            side_effect=Exception("DB locked")
        )
        mock_txn.return_value.__exit__ = MagicMock(return_value=False)

        paper = {"arxiv_id": "2401.00001", "title": "Test", "stage": "discovered"}
        result = upsert_paper("/tmp/test.db", paper)
        assert result is None

    @patch("services.discovery.main.transaction")
    def test_fetchone_none_returns_none(self, mock_txn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn.execute.return_value = mock_cursor
        mock_txn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_txn.return_value.__exit__ = MagicMock(return_value=False)

        paper = {"arxiv_id": "2401.00001", "title": "Test", "stage": "discovered"}
        result = upsert_paper("/tmp/test.db", paper)
        assert result is None


# ---------------------------------------------------------------------------
# TestUpdatePaperS2
# ---------------------------------------------------------------------------


class TestUpdatePaperS2:
    """Tests for update_paper_s2() — mock transaction."""

    @patch("services.discovery.main.transaction")
    def test_standard_update_returns_true(self, mock_txn):
        mock_conn = MagicMock()
        mock_txn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_txn.return_value.__exit__ = MagicMock(return_value=False)

        enrichment = {
            "semantic_scholar_id": "abc123",
            "citation_count": 42,
            "reference_count": 15,
            "influential_citation_count": 5,
            "venue": "NIPS",
            "fields_of_study": '["CS"]',
            "tldr": "Summary",
            "open_access": 1,
        }
        result = update_paper_s2("/tmp/test.db", 1, enrichment)
        assert result is True
        sql = mock_conn.execute.call_args[0][0]
        assert "doi" not in sql.split("SET")[1].split("WHERE")[0]

    @patch("services.discovery.main.transaction")
    def test_update_with_doi(self, mock_txn):
        mock_conn = MagicMock()
        mock_txn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_txn.return_value.__exit__ = MagicMock(return_value=False)

        enrichment = {
            "semantic_scholar_id": "abc123",
            "citation_count": 42,
            "reference_count": 15,
            "influential_citation_count": 5,
            "venue": "NIPS",
            "fields_of_study": '["CS"]',
            "tldr": "Summary",
            "open_access": 1,
            "doi": "10.1234/journal",
        }
        result = update_paper_s2("/tmp/test.db", 1, enrichment)
        assert result is True
        sql = mock_conn.execute.call_args[0][0]
        assert "doi=?" in sql

    @patch("services.discovery.main.transaction")
    def test_update_without_doi_excludes_column(self, mock_txn):
        mock_conn = MagicMock()
        mock_txn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_txn.return_value.__exit__ = MagicMock(return_value=False)

        enrichment = {
            "semantic_scholar_id": "abc123",
            "citation_count": 0,
            "reference_count": 0,
            "influential_citation_count": 0,
            "venue": "",
            "fields_of_study": "[]",
            "tldr": None,
            "open_access": 0,
        }
        result = update_paper_s2("/tmp/test.db", 1, enrichment)
        assert result is True
        # Verify 9 values: 8 columns + paper_id
        values = mock_conn.execute.call_args[0][1]
        assert len(values) == 9

    @patch("services.discovery.main.transaction")
    def test_db_error_returns_false(self, mock_txn):
        mock_txn.return_value.__enter__ = MagicMock(
            side_effect=Exception("DB error")
        )
        mock_txn.return_value.__exit__ = MagicMock(return_value=False)

        result = update_paper_s2("/tmp/test.db", 1, {"semantic_scholar_id": "x"})
        assert result is False


# ---------------------------------------------------------------------------
# TestUpdatePaperCrossref
# ---------------------------------------------------------------------------


class TestUpdatePaperCrossref:
    """Tests for update_paper_crossref() — mock transaction."""

    @patch("services.discovery.main.transaction")
    def test_valid_update_returns_true(self, mock_txn):
        mock_conn = MagicMock()
        mock_txn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_txn.return_value.__exit__ = MagicMock(return_value=False)

        cr_data = {"DOI": "10.1234/test", "title": ["Test"]}
        result = update_paper_crossref("/tmp/test.db", 1, cr_data)
        assert result is True
        # Verify JSON serialization
        args = mock_conn.execute.call_args[0][1]
        assert json.loads(args[0]) == cr_data

    @patch("services.discovery.main.transaction")
    def test_json_serialization(self, mock_txn):
        mock_conn = MagicMock()
        mock_txn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_txn.return_value.__exit__ = MagicMock(return_value=False)

        cr_data = {"nested": {"key": [1, 2, 3]}}
        update_paper_crossref("/tmp/test.db", 1, cr_data)
        args = mock_conn.execute.call_args[0][1]
        assert json.loads(args[0]) == cr_data

    @patch("services.discovery.main.transaction")
    def test_db_error_returns_false(self, mock_txn):
        mock_txn.return_value.__enter__ = MagicMock(
            side_effect=Exception("DB error")
        )
        mock_txn.return_value.__exit__ = MagicMock(return_value=False)

        result = update_paper_crossref("/tmp/test.db", 1, {"key": "value"})
        assert result is False


# ---------------------------------------------------------------------------
# TestDiscoveryHandlerValidation
# ---------------------------------------------------------------------------


class TestDiscoveryHandlerValidation:
    """Tests for DiscoveryHandler input validation in handle_process()."""

    def _make_handler(self):
        """Create a mock DiscoveryHandler for testing validation."""
        from services.discovery.main import DiscoveryHandler

        handler = MagicMock(spec=DiscoveryHandler)
        handler.db_path = "/tmp/test.db"
        handler.send_error_json = MagicMock()
        return handler

    def test_missing_query_returns_422(self):
        handler = self._make_handler()
        from services.discovery.main import DiscoveryHandler

        DiscoveryHandler.handle_process(handler, {})
        handler.send_error_json.assert_called_once()
        args = handler.send_error_json.call_args
        assert args[0][1] == "VALIDATION_ERROR"
        assert args[0][2] == 422

    def test_empty_query_returns_422(self):
        handler = self._make_handler()
        from services.discovery.main import DiscoveryHandler

        DiscoveryHandler.handle_process(handler, {"query": ""})
        handler.send_error_json.assert_called_once()

    def test_non_string_query_returns_422(self):
        handler = self._make_handler()
        from services.discovery.main import DiscoveryHandler

        DiscoveryHandler.handle_process(handler, {"query": 123})
        handler.send_error_json.assert_called_once()

    def test_invalid_max_results_zero(self):
        handler = self._make_handler()
        from services.discovery.main import DiscoveryHandler

        DiscoveryHandler.handle_process(
            handler, {"query": "test", "max_results": 0}
        )
        handler.send_error_json.assert_called_once()
        assert handler.send_error_json.call_args[0][2] == 422

    def test_invalid_max_results_over_500(self):
        handler = self._make_handler()
        from services.discovery.main import DiscoveryHandler

        DiscoveryHandler.handle_process(
            handler, {"query": "test", "max_results": 501}
        )
        handler.send_error_json.assert_called_once()

    def test_invalid_max_results_string(self):
        handler = self._make_handler()
        from services.discovery.main import DiscoveryHandler

        DiscoveryHandler.handle_process(
            handler, {"query": "test", "max_results": "ten"}
        )
        handler.send_error_json.assert_called_once()

    @patch("services.discovery.main.search_arxiv", return_value=[])
    def test_valid_defaults_no_max_results(self, mock_search):
        handler = self._make_handler()
        from services.discovery.main import DiscoveryHandler

        DiscoveryHandler.handle_process(handler, {"query": "test"})
        mock_search.assert_called_once_with("test", DEFAULT_MAX_RESULTS)
