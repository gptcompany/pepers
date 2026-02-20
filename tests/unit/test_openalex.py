"""Unit tests for services/discovery/openalex.py — all external calls mocked."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from services.discovery.openalex import (
    _reconstruct_abstract,
    _extract_arxiv_id_from_locations,
    _strip_openalex_url,
    search_openalex,
    upsert_openalex_paper,
)


# ---------------------------------------------------------------------------
# TestReconstructAbstract
# ---------------------------------------------------------------------------


class TestReconstructAbstract:
    """Tests for _reconstruct_abstract()."""

    def test_basic_reconstruction(self):
        inv = {"Hello": [0], "world": [1]}
        assert _reconstruct_abstract(inv) == "Hello world"

    def test_multiple_positions(self):
        inv = {"the": [0, 3], "cat": [1], "sat": [2], "mat": [4]}
        assert _reconstruct_abstract(inv) == "the cat sat the mat"

    def test_none_input(self):
        assert _reconstruct_abstract(None) is None

    def test_empty_dict(self):
        assert _reconstruct_abstract({}) is None

    def test_single_word(self):
        assert _reconstruct_abstract({"hello": [0]}) == "hello"


# ---------------------------------------------------------------------------
# TestExtractArxivIdFromLocations
# ---------------------------------------------------------------------------


class TestExtractArxivIdFromLocations:
    """Tests for _extract_arxiv_id_from_locations()."""

    def test_finds_arxiv_from_source_name(self):
        locations = [
            {
                "source": {"display_name": "arXiv"},
                "landing_page_url": "https://arxiv.org/abs/2401.12345",
            }
        ]
        assert _extract_arxiv_id_from_locations(locations) == "2401.12345"

    def test_finds_arxiv_from_pdf_url(self):
        locations = [
            {
                "source": {"display_name": "Other"},
                "pdf_url": "https://arxiv.org/pdf/2301.99999",
            }
        ]
        assert _extract_arxiv_id_from_locations(locations) == "2301.99999"

    def test_no_arxiv_returns_none(self):
        locations = [
            {
                "source": {"display_name": "PubMed Central"},
                "landing_page_url": "https://pubmed.ncbi.nlm.nih.gov/12345",
            }
        ]
        assert _extract_arxiv_id_from_locations(locations) is None

    def test_empty_locations(self):
        assert _extract_arxiv_id_from_locations([]) is None

    def test_missing_source_key(self):
        locations = [{"landing_page_url": "https://example.com"}]
        assert _extract_arxiv_id_from_locations(locations) is None


# ---------------------------------------------------------------------------
# TestStripOpenalexUrl
# ---------------------------------------------------------------------------


class TestStripOpenalexUrl:
    """Tests for _strip_openalex_url()."""

    def test_full_url(self):
        assert _strip_openalex_url("https://openalex.org/W2741809807") == "W2741809807"

    def test_already_short(self):
        assert _strip_openalex_url("W2741809807") == "W2741809807"

    def test_empty_string(self):
        assert _strip_openalex_url("") == ""


# ---------------------------------------------------------------------------
# TestSearchOpenalex
# ---------------------------------------------------------------------------


class TestSearchOpenalex:
    """Tests for search_openalex() — mock requests.get."""

    SAMPLE_WORK = {
        "id": "https://openalex.org/W2741809807",
        "display_name": "Kelly Criterion in Practice",
        "abstract_inverted_index": {"Kelly": [0], "criterion": [1], "paper": [2]},
        "authorships": [
            {"author": {"display_name": "Alice Smith"}},
            {"author": {"display_name": "Bob Jones"}},
        ],
        "primary_topic": {
            "field": {"display_name": "Economics"},
            "subfield": {"display_name": "Finance"},
        },
        "doi": "https://doi.org/10.1234/test.2024",
        "open_access": {"oa_url": "https://example.com/paper.pdf"},
        "publication_date": "2024-03-15",
        "cited_by_count": 42,
        "referenced_works_count": 25,
        "locations": [
            {
                "source": {"display_name": "arXiv"},
                "landing_page_url": "https://arxiv.org/abs/2401.00001",
            }
        ],
    }

    @patch("services.discovery.openalex.requests.get")
    def test_basic_search_returns_papers(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"results": [self.SAMPLE_WORK]}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        papers = search_openalex("Kelly criterion", max_results=10)
        assert len(papers) == 1
        p = papers[0]
        assert p["openalex_id"] == "W2741809807"
        assert p["title"] == "Kelly Criterion in Practice"
        assert p["abstract"] == "Kelly criterion paper"
        assert json.loads(p["authors"]) == ["Alice Smith", "Bob Jones"]
        assert p["doi"] == "10.1234/test.2024"
        assert p["pdf_url"] == "https://example.com/paper.pdf"
        assert p["citation_count"] == 42
        assert p["reference_count"] == 25
        assert p["arxiv_id"] == "2401.00001"
        assert p["source"] == "openalex"
        assert p["stage"] == "discovered"

    @patch("services.discovery.openalex.requests.get")
    def test_categories_extracted(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": [self.SAMPLE_WORK]}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        papers = search_openalex("test", max_results=5)
        cats = json.loads(papers[0]["categories"])
        assert "Economics" in cats
        assert "Finance" in cats

    @patch("services.discovery.openalex.requests.get")
    def test_doi_prefix_stripped(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": [self.SAMPLE_WORK]}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        papers = search_openalex("test")
        assert papers[0]["doi"] == "10.1234/test.2024"
        assert not papers[0]["doi"].startswith("https://")

    @patch("services.discovery.openalex.requests.get")
    def test_empty_results(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": []}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        papers = search_openalex("nonexistent", max_results=10)
        assert papers == []

    @patch("services.discovery.openalex.requests.get")
    def test_missing_optional_fields(self, mock_get):
        work = {
            "id": "https://openalex.org/W999",
            "display_name": "Minimal Paper",
            "abstract_inverted_index": None,
            "authorships": [],
            "primary_topic": None,
            "doi": None,
            "open_access": None,
            "publication_date": None,
            "cited_by_count": 0,
            "referenced_works_count": 0,
            "locations": [],
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": [work]}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        papers = search_openalex("test")
        assert len(papers) == 1
        p = papers[0]
        assert p["abstract"] is None
        assert json.loads(p["authors"]) == []
        assert json.loads(p["categories"]) == []
        assert p["doi"] is None
        assert p["pdf_url"] is None
        assert p["arxiv_id"] is None

    @patch("services.discovery.openalex.requests.get")
    def test_skips_works_without_id(self, mock_get):
        work = {"display_name": "No ID Paper"}
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": [work]}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        papers = search_openalex("test")
        assert papers == []

    @patch("services.discovery.openalex.requests.get")
    def test_skips_works_without_title(self, mock_get):
        work = {"id": "https://openalex.org/W999", "display_name": ""}
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": [work]}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        papers = search_openalex("test")
        assert papers == []

    @patch("services.discovery.openalex.requests.get")
    def test_request_error_raises(self, mock_get):
        mock_get.side_effect = requests.RequestException("Timeout")
        with pytest.raises(requests.RequestException):
            search_openalex("test")

    @patch("services.discovery.openalex.requests.get")
    def test_mailto_param_sent(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": []}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        search_openalex("test", max_results=10)
        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["params"]["mailto"] == "gptprojectmanager@gmail.com"

    @patch("services.discovery.openalex.requests.get")
    def test_max_results_caps_per_page(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": []}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        search_openalex("test", max_results=300)
        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["params"]["per_page"] == 200


# ---------------------------------------------------------------------------
# TestUpsertOpenalexPaper
# ---------------------------------------------------------------------------


class TestUpsertOpenalexPaper:
    """Tests for upsert_openalex_paper() — mock DB."""

    @patch("services.discovery.openalex.transaction")
    def test_new_paper_returns_id(self, mock_txn):
        mock_conn = MagicMock()
        # No existing arXiv paper
        mock_cursor_select = MagicMock()
        mock_cursor_select.fetchone.return_value = None
        mock_cursor_insert = MagicMock()
        mock_cursor_insert.fetchone.return_value = (42,)
        mock_conn.execute.side_effect = [mock_cursor_select, mock_cursor_insert]
        mock_txn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_txn.return_value.__exit__ = MagicMock(return_value=False)

        paper = {
            "openalex_id": "W123",
            "arxiv_id": "2401.00001",
            "title": "Test",
            "abstract": "Abstract",
            "authors": '["A"]',
            "categories": '["CS"]',
            "doi": "10.1234/test",
            "pdf_url": None,
            "published_date": "2024-01-15",
            "citation_count": 10,
            "reference_count": 5,
            "source": "openalex",
            "stage": "discovered",
        }
        result = upsert_openalex_paper("/tmp/test.db", paper)
        assert result == 42

    @patch("services.discovery.openalex.transaction")
    def test_cross_dedup_updates_existing_arxiv_paper(self, mock_txn):
        mock_conn = MagicMock()
        # Existing arXiv paper found
        mock_cursor_select = MagicMock()
        mock_cursor_select.fetchone.return_value = {"id": 7}
        mock_cursor_update = MagicMock()
        mock_conn.execute.side_effect = [mock_cursor_select, mock_cursor_update]
        mock_txn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_txn.return_value.__exit__ = MagicMock(return_value=False)

        paper = {
            "openalex_id": "W456",
            "arxiv_id": "2401.00001",
            "title": "Test",
            "source": "openalex",
            "citation_count": 20,
            "reference_count": 10,
        }
        result = upsert_openalex_paper("/tmp/test.db", paper)
        assert result == 7
        # Verify UPDATE was called (not INSERT)
        update_call = mock_conn.execute.call_args_list[1]
        assert "UPDATE papers SET openalex_id" in update_call[0][0]

    @patch("services.discovery.openalex.transaction")
    def test_no_arxiv_id_skips_dedup(self, mock_txn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1,)
        mock_conn.execute.return_value = mock_cursor
        mock_txn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_txn.return_value.__exit__ = MagicMock(return_value=False)

        paper = {
            "openalex_id": "W789",
            "arxiv_id": None,
            "title": "No arXiv link",
            "source": "openalex",
            "stage": "discovered",
        }
        result = upsert_openalex_paper("/tmp/test.db", paper)
        assert result == 1
        # Should NOT query for existing arxiv paper
        sql = mock_conn.execute.call_args[0][0]
        assert "INSERT INTO papers" in sql

    @patch("services.discovery.openalex.transaction")
    def test_db_error_returns_none(self, mock_txn):
        mock_txn.return_value.__enter__ = MagicMock(
            side_effect=Exception("DB locked")
        )
        mock_txn.return_value.__exit__ = MagicMock(return_value=False)

        paper = {"openalex_id": "W999", "title": "Test", "source": "openalex"}
        result = upsert_openalex_paper("/tmp/test.db", paper)
        assert result is None


# ---------------------------------------------------------------------------
# TestDiscoverySources
# ---------------------------------------------------------------------------


class TestDiscoverySources:
    """Tests for RP_DISCOVERY_SOURCES parsing in handler."""

    def test_default_sources_is_arxiv(self):
        from services.discovery.main import DEFAULT_SOURCES
        assert "arxiv" in DEFAULT_SOURCES

    def test_valid_sources_set(self):
        from services.discovery.main import VALID_SOURCES
        assert "arxiv" in VALID_SOURCES
        assert "openalex" in VALID_SOURCES

    def test_handler_rejects_invalid_source(self):
        from services.discovery.main import DiscoveryHandler

        handler = MagicMock(spec=DiscoveryHandler)
        handler.db_path = "/tmp/test.db"
        handler.send_error_json = MagicMock()

        DiscoveryHandler.handle_process(
            handler, {"query": "test", "sources": ["invalid_source"]}
        )
        handler.send_error_json.assert_called_once()
        args = handler.send_error_json.call_args
        assert args[0][1] == "VALIDATION_ERROR"

    @patch("services.discovery.main.search_arxiv", return_value=[])
    def test_handler_accepts_arxiv_source(self, mock_search):
        from services.discovery.main import DiscoveryHandler

        handler = MagicMock(spec=DiscoveryHandler)
        handler.db_path = "/tmp/test.db"
        handler.send_error_json = MagicMock()

        result = DiscoveryHandler.handle_process(
            handler, {"query": "test", "sources": ["arxiv"]}
        )
        assert result["sources"] == ["arxiv"]
        assert result["papers_found"] == 0

    @patch("services.discovery.openalex.requests.get")
    @patch("services.discovery.main.search_arxiv", return_value=[])
    def test_handler_accepts_both_sources(self, mock_search, mock_oa_get):
        from services.discovery.main import DiscoveryHandler

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": []}
        mock_resp.raise_for_status = MagicMock()
        mock_oa_get.return_value = mock_resp

        handler = MagicMock(spec=DiscoveryHandler)
        handler.db_path = "/tmp/test.db"
        handler.send_error_json = MagicMock()

        result = DiscoveryHandler.handle_process(
            handler, {"query": "test", "sources": ["arxiv", "openalex"]}
        )
        assert set(result["sources"]) == {"arxiv", "openalex"}
