"""Integration tests for OpenAlex discovery — real SQLite DB, mock HTTP APIs."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from shared.db import transaction
from services.discovery.openalex import upsert_openalex_paper
from services.discovery.main import upsert_paper


# ---------------------------------------------------------------------------
# TestUpsertOpenalexPaperDB — real SQLite
# ---------------------------------------------------------------------------


class TestUpsertOpenalexPaperDB:
    """Integration tests for upsert_openalex_paper() with real SQLite."""

    def _make_oa_paper(self, openalex_id="W123", arxiv_id=None, title="OA Paper"):
        return {
            "openalex_id": openalex_id,
            "arxiv_id": arxiv_id,
            "title": title,
            "abstract": "OpenAlex abstract",
            "authors": json.dumps(["Author A"]),
            "categories": json.dumps(["Computer Science"]),
            "doi": "10.1234/oa.test",
            "pdf_url": "https://example.com/paper.pdf",
            "published_date": "2024-06-01",
            "citation_count": 15,
            "reference_count": 8,
            "source": "openalex",
            "stage": "discovered",
        }

    def test_insert_new_openalex_paper(self, initialized_db):
        paper = self._make_oa_paper()
        paper_id = upsert_openalex_paper(str(initialized_db), paper)
        assert paper_id is not None

        with transaction(str(initialized_db)) as conn:
            row = conn.execute(
                "SELECT * FROM papers WHERE id=?", (paper_id,)
            ).fetchone()
        assert row["openalex_id"] == "W123"
        assert row["title"] == "OA Paper"
        assert row["source"] == "openalex"
        assert row["arxiv_id"] is None

    def test_upsert_updates_existing_openalex_paper(self, initialized_db):
        paper = self._make_oa_paper()
        id1 = upsert_openalex_paper(str(initialized_db), paper)

        updated = self._make_oa_paper(title="Updated OA Paper")
        updated["citation_count"] = 99
        id2 = upsert_openalex_paper(str(initialized_db), updated)

        assert id1 == id2

        with transaction(str(initialized_db)) as conn:
            row = conn.execute(
                "SELECT * FROM papers WHERE id=?", (id1,)
            ).fetchone()
        assert row["title"] == "Updated OA Paper"
        assert row["citation_count"] == 99

    def test_cross_source_dedup_arxiv_then_openalex(self, initialized_db):
        """Paper discovered via arXiv first, then found on OpenAlex — should merge."""
        # Insert via arXiv
        arxiv_paper = {
            "arxiv_id": "2401.00001",
            "title": "Kelly Criterion Paper",
            "abstract": "arXiv abstract",
            "authors": json.dumps(["Alice"]),
            "categories": json.dumps(["q-fin.PM"]),
            "doi": None,
            "pdf_url": "https://arxiv.org/pdf/2401.00001",
            "published_date": "2024-01-15",
            "source": "arxiv",
            "stage": "discovered",
        }
        arxiv_id = upsert_paper(str(initialized_db), arxiv_paper)
        assert arxiv_id is not None

        # Now same paper found via OpenAlex (with arxiv_id cross-link)
        oa_paper = self._make_oa_paper(
            openalex_id="W555",
            arxiv_id="2401.00001",
            title="Kelly Criterion Paper (OpenAlex)",
        )
        oa_id = upsert_openalex_paper(str(initialized_db), oa_paper)

        # Should return the SAME paper_id
        assert oa_id == arxiv_id

        # Should have openalex_id set on the existing row
        with transaction(str(initialized_db)) as conn:
            row = conn.execute(
                "SELECT * FROM papers WHERE id=?", (arxiv_id,)
            ).fetchone()
        assert row["openalex_id"] == "W555"
        assert row["arxiv_id"] == "2401.00001"
        # Source stays as original (arxiv)
        assert row["source"] == "arxiv"

    def test_cross_source_dedup_openalex_then_arxiv(self, initialized_db):
        """Paper discovered via OpenAlex first, then found on arXiv — separate rows."""
        # Insert via OpenAlex (no arxiv_id initially)
        oa_paper = self._make_oa_paper(openalex_id="W777", arxiv_id=None)
        oa_id = upsert_openalex_paper(str(initialized_db), oa_paper)

        # Insert via arXiv (different paper row, since OA had no arxiv_id)
        arxiv_paper = {
            "arxiv_id": "2401.00002",
            "title": "Different Paper",
            "abstract": "Different abstract",
            "authors": json.dumps(["Bob"]),
            "categories": json.dumps(["stat.ML"]),
            "doi": None,
            "pdf_url": None,
            "published_date": "2024-02-01",
            "source": "arxiv",
            "stage": "discovered",
        }
        arxiv_id = upsert_paper(str(initialized_db), arxiv_paper)

        assert oa_id != arxiv_id

        with transaction(str(initialized_db)) as conn:
            count = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        assert count == 2

    def test_multiple_openalex_papers(self, initialized_db):
        for i in range(5):
            paper = self._make_oa_paper(
                openalex_id=f"W{100 + i}",
                title=f"Paper {i}",
            )
            pid = upsert_openalex_paper(str(initialized_db), paper)
            assert pid is not None

        with transaction(str(initialized_db)) as conn:
            count = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        assert count == 5

    def test_openalex_paper_with_null_optional_fields(self, initialized_db):
        paper = {
            "openalex_id": "W888",
            "arxiv_id": None,
            "title": "Minimal OA Paper",
            "abstract": None,
            "authors": None,
            "categories": None,
            "doi": None,
            "pdf_url": None,
            "published_date": None,
            "citation_count": 0,
            "reference_count": 0,
            "source": "openalex",
            "stage": "discovered",
        }
        pid = upsert_openalex_paper(str(initialized_db), paper)
        assert pid is not None

        with transaction(str(initialized_db)) as conn:
            row = conn.execute(
                "SELECT * FROM papers WHERE id=?", (pid,)
            ).fetchone()
        assert row["abstract"] is None
        assert row["doi"] is None
        assert row["source"] == "openalex"


# ---------------------------------------------------------------------------
# TestHandlerWithOpenalexSource — real DB, mock HTTP
# ---------------------------------------------------------------------------


class TestHandlerWithOpenalexSource:
    """Integration tests for handler with sources=["openalex"]."""

    @patch("services.discovery.openalex.requests.get")
    def test_handler_openalex_only(self, mock_get, initialized_db):
        from services.discovery.main import DiscoveryHandler

        sample_work = {
            "id": "https://openalex.org/W111",
            "display_name": "OpenAlex Test Paper",
            "abstract_inverted_index": {"Test": [0], "abstract": [1]},
            "authorships": [{"author": {"display_name": "Test Author"}}],
            "primary_topic": {"field": {"display_name": "CS"}, "subfield": None},
            "doi": "https://doi.org/10.1234/oa",
            "open_access": {"oa_url": None},
            "publication_date": "2024-06-01",
            "cited_by_count": 5,
            "referenced_works_count": 3,
            "locations": [],
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": [sample_work]}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        handler = MagicMock(spec=DiscoveryHandler)
        handler.db_path = str(initialized_db)
        handler.send_error_json = MagicMock()

        result = DiscoveryHandler.handle_process(
            handler, {"query": "test", "sources": ["openalex"]}
        )

        assert result["papers_found"] == 1
        assert "openalex" in result["sources"]

        # Verify paper in DB
        with transaction(str(initialized_db)) as conn:
            row = conn.execute(
                "SELECT * FROM papers WHERE openalex_id='W111'"
            ).fetchone()
        assert row is not None
        assert row["title"] == "OpenAlex Test Paper"
        assert row["source"] == "openalex"
