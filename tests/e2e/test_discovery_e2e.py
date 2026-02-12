"""End-to-end tests for Discovery service — real API calls.

These tests make real HTTP requests to arXiv, Semantic Scholar, and CrossRef.
They require network access and are skipped by default in CI.

Run with: pytest tests/e2e/ -m e2e -v
"""

from __future__ import annotations

import json

import pytest

from shared.db import init_db, transaction
from services.discovery.main import (
    search_arxiv,
    enrich_s2,
    enrich_crossref,
    upsert_paper,
    update_paper_s2,
    update_paper_crossref,
)

pytestmark = pytest.mark.e2e


@pytest.fixture
def e2e_db(tmp_path):
    """Temporary SQLite database for E2E tests."""
    db_path = tmp_path / "e2e_research.db"
    init_db(db_path)
    return str(db_path)


class TestDiscoveryE2E:
    """End-to-end tests with real API calls."""

    def test_search_arxiv_kelly_criterion(self):
        """Search arXiv for Kelly criterion papers — real API."""
        papers = search_arxiv('abs:"Kelly criterion"', max_results=3)
        assert len(papers) > 0
        for p in papers:
            assert p["arxiv_id"]
            assert p["title"]
            assert p["stage"] == "discovered"
            # Authors and categories should be valid JSON
            assert isinstance(json.loads(p["authors"]), list)
            assert isinstance(json.loads(p["categories"]), list)

    def test_enrich_s2_known_paper(self):
        """Enrich a known paper with Semantic Scholar — real API."""
        # 2107.05580 = "Universal portfolios" by Cover (well-known)
        result = enrich_s2("2107.05580")
        # May return None if S2 doesn't have it, but if found, check structure
        if result is not None:
            assert "semantic_scholar_id" in result
            assert isinstance(result["citation_count"], int)
            assert isinstance(result["reference_count"], int)

    def test_enrich_crossref_known_doi(self):
        """Enrich a known DOI with CrossRef — real API."""
        # Well-known paper DOI
        result = enrich_crossref("10.1103/PhysRevLett.116.061102")
        if result is not None:
            assert "DOI" in result or "title" in result

    def test_full_pipeline_real_apis(self, e2e_db):
        """Full pipeline: arXiv search → DB → S2 enrich → CrossRef enrich."""
        papers = search_arxiv('abs:"Kelly criterion" AND cat:q-fin.*', max_results=2)

        if not papers:
            pytest.skip("No papers returned from arXiv")

        for paper in papers:
            paper_id = upsert_paper(e2e_db, paper)
            assert paper_id is not None

            s2_data = enrich_s2(paper["arxiv_id"])
            if s2_data:
                assert update_paper_s2(e2e_db, paper_id, s2_data) is True

            doi = paper.get("doi")
            if not doi and s2_data and "doi" in s2_data:
                doi = s2_data["doi"]
            if doi:
                cr_data = enrich_crossref(doi)
                if cr_data:
                    assert update_paper_crossref(e2e_db, paper_id, cr_data) is True

        # Verify data in DB
        with transaction(e2e_db) as conn:
            count = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        assert count == len(papers)

    def test_idempotent_upsert(self, e2e_db):
        """Second upsert of same paper doesn't duplicate."""
        papers = search_arxiv('abs:"Kelly criterion"', max_results=1)
        if not papers:
            pytest.skip("No papers returned from arXiv")

        paper = papers[0]
        id1 = upsert_paper(e2e_db, paper)
        id2 = upsert_paper(e2e_db, paper)
        assert id1 == id2

        with transaction(e2e_db) as conn:
            count = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        assert count == 1
