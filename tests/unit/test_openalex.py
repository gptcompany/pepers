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
        index = {"The": [0], "Kelly": [1], "criterion": [2], "is": [3], "optimal": [4]}
        assert _reconstruct_abstract(index) == "The Kelly criterion is optimal"

    def test_repeated_words(self):
        index = {"the": [0, 3], "dog": [1], "chased": [2]}
        assert _reconstruct_abstract(index) == "the dog chased the"

    def test_empty_input(self):
        assert _reconstruct_abstract(None) is None
        assert _reconstruct_abstract({}) is None

    def test_unordered_index(self):
        # Index keys are not necessarily in order
        index = {"optimal": [4], "The": [0], "is": [3], "Kelly": [1], "criterion": [2]}
        assert _reconstruct_abstract(index) == "The Kelly criterion is optimal"


# ---------------------------------------------------------------------------
# TestExtractArxivIdFromLocations
# ---------------------------------------------------------------------------


class TestExtractArxivIdFromLocations:
    """Tests for _extract_arxiv_id_from_locations()."""

    def test_extract_from_landing_page_url(self):
        locations = [
            {
                "source": {"display_name": "arXiv"},
                "landing_page_url": "https://arxiv.org/abs/2107.05580",
            }
        ]
        assert _extract_arxiv_id_from_locations(locations) == "2107.05580"

    def test_extract_from_pdf_url(self):
        locations = [
            {
                "source": {"display_name": "other"},
                "pdf_url": "https://arxiv.org/pdf/2401.12345",
            }
        ]
        assert _extract_arxiv_id_from_locations(locations) == "2401.12345"

    def test_no_arxiv_location(self):
        locations = [
            {
                "source": {"display_name": "Nature"},
                "landing_page_url": "https://nature.com/articles/123",
            }
        ]
        assert _extract_arxiv_id_from_locations(locations) is None

    def test_empty_locations(self):
        assert _extract_arxiv_id_from_locations([]) is None


# ---------------------------------------------------------------------------
# TestSearchOpenAlex
# ---------------------------------------------------------------------------


class TestSearchOpenAlex:
    """Tests for search_openalex() — mock requests.get."""

    @patch("services.discovery.openalex.requests.get")
    def test_search_returns_paper_dicts(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [
                {
                    "id": "https://openalex.org/W123",
                    "display_name": "Test Paper",
                    "abstract_inverted_index": {"Abstract": [0]},
                    "authorships": [{"author": {"display_name": "Author A"}}],
                    "primary_topic": {"field": {"display_name": "Math"}},
                    "doi": "https://doi.org/10.1234/test",
                    "open_access": {"oa_url": "http://pdf"},
                    "publication_date": "2024-01-01",
                    "cited_by_count": 10,
                }
            ]
        }
        mock_get.return_value = mock_resp

        papers = search_openalex("query", 10)
        assert len(papers) == 1
        p = papers[0]
        assert p["openalex_id"] == "W123"
        assert p["title"] == "Test Paper"
        assert p["doi"] == "10.1234/test"
        assert p["source"] == "openalex"
        assert json.loads(p["authors"]) == ["Author A"]

    @patch("services.discovery.openalex.requests.get")
    def test_request_failure_raises(self, mock_get):
        mock_get.side_effect = requests.RequestException("error")
        with pytest.raises(requests.RequestException):
            search_openalex("q")


# ---------------------------------------------------------------------------
# TestUpsertOpenAlexPaper
# ---------------------------------------------------------------------------


class TestUpsertOpenAlexPaper:
    """Tests for upsert_openalex_paper() — mock transaction."""

    @patch("services.discovery.openalex.transaction")
    def test_upsert_new_paper(self, mock_txn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (10,)
        mock_conn.execute.return_value = mock_cursor
        mock_txn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        
        paper = {"openalex_id": "W1", "title": "T", "source": "openalex"}
        res = upsert_openalex_paper("/tmp/db", paper)
        assert res == 10

    @patch("services.discovery.openalex.transaction")
    def test_upsert_cross_source_dedup_with_arxiv(self, mock_txn):
        mock_conn = MagicMock()
        # First call: SELECT returns existing arxiv paper id=5
        mock_conn.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value={"id": 5})),
            MagicMock() # UPDATE call
        ]
        mock_txn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        
        paper = {"openalex_id": "W1", "arxiv_id": "2401.00001", "title": "T"}
        res = upsert_openalex_paper("/tmp/db", paper)
        
        assert res == 5
        # Verify UPDATE was called instead of INSERT
        sql = mock_conn.execute.call_args_list[1][0][0]
        assert "UPDATE papers SET openalex_id=?" in sql

    @patch("services.discovery.openalex.transaction")
    def test_db_error_returns_none(self, mock_txn):
        mock_txn.return_value.__enter__ = MagicMock(side_effect=Exception("err"))
        res = upsert_openalex_paper("/tmp/db", {"openalex_id": "W1"})
        assert res is None
