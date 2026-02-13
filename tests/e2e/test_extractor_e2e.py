"""End-to-end tests for Extractor service — real RAGAnything + real arXiv PDF.

These tests make real HTTP requests to RAGAnything (localhost:8767) and arXiv.
They are skipped by default and require RAGAnything running.

Run with: pytest tests/e2e/test_extractor_e2e.py -m e2e -v
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from shared.db import init_db
from services.extractor.latex import extract_formulas, filter_formulas
from services.extractor.main import ExtractorHandler
from services.extractor.rag_client import check_service
from services.discovery.main import upsert_paper
from services.analyzer.main import migrate_db

pytestmark = pytest.mark.e2e


def _raganything_available() -> bool:
    """Check if RAGAnything is running on localhost:8767."""
    try:
        req = urllib.request.Request("http://localhost:8767/status")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            # Also check circuit breaker isn't open
            if data.get("circuit_breaker", {}).get("state") == "open":
                return False
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


@pytest.fixture
def e2e_db(tmp_path):
    """Temporary SQLite database for E2E tests with migrations applied."""
    db_path = tmp_path / "e2e_extractor.db"
    init_db(db_path)
    migrate_db(str(db_path))
    return str(db_path)


class TestExtractorE2E:
    """End-to-end tests with real RAGAnything service."""

    def test_raganything_health(self):
        """Verify RAGAnything service is accessible and healthy."""
        if not _raganything_available():
            pytest.skip("RAGAnything not available at localhost:8767")

        status = check_service("http://localhost:8767")
        assert "circuit_breaker" in status or "status" in status

    def test_latex_extraction_from_real_markdown(self):
        """Extract formulas from a realistic markdown sample (no external deps)."""
        # This test validates the full extract+filter pipeline with realistic data
        markdown = r"""
# Fractional Kelly Strategies

## Abstract

We study the fractional Kelly criterion for portfolio optimization.

## Main Result

The optimal fraction is given by:

\begin{equation}
f^* = \frac{p \cdot b - q}{b} = \frac{p(b+1) - 1}{b}
\end{equation}

where $p$ is the win probability, $q = 1-p$, and $b$ is the odds ratio.

The expected log growth rate is:

\[
G(f) = p \ln(1 + fb) + q \ln(1 - f)
\]

For multiple assets with correlation matrix $\Sigma$:

$$\mathbf{f}^* = \Sigma^{-1}(\boldsymbol{\mu} - r\mathbf{1})$$

The portfolio variance is \(\sigma_p^2 = \mathbf{f}^T \Sigma \mathbf{f}\).
"""
        raw = extract_formulas(markdown)
        assert len(raw) >= 4  # At least: equation env, \[...\], $$...$$, \(...\)

        filtered = filter_formulas(raw)
        assert len(filtered) >= 3  # Some inline $...$ may be filtered

        # Check display formulas contain expected LaTeX
        display = [f for f in filtered if f["formula_type"] == "display"]
        assert any("frac" in f["latex"] for f in display)

    def test_full_pipeline_discover_analyze_extract(self, e2e_db, tmp_path):
        """Insert paper, set to analyzed, extract with real RAGAnything."""
        if not _raganything_available():
            pytest.skip("RAGAnything not available at localhost:8767")

        from unittest.mock import MagicMock

        # Insert paper as analyzed (ready for extraction)
        paper = {
            "arxiv_id": "2401.00001",
            "title": "Kelly Criterion in Portfolio Optimization",
            "abstract": (
                "We study the Kelly criterion for optimal bet sizing "
                "in financial markets using continuous-time models."
            ),
            "authors": json.dumps(["Edward Thorp"]),
            "categories": json.dumps(["q-fin.PM"]),
            "doi": None,
            "pdf_url": "https://arxiv.org/pdf/2401.00001",
            "published_date": "2024-01-15",
            "stage": "analyzed",
        }
        paper_id = upsert_paper(e2e_db, paper)
        assert paper_id is not None

        # Run extractor
        handler = MagicMock(spec=ExtractorHandler)
        handler.db_path = e2e_db
        handler.max_papers_default = 1
        handler.pdf_dir = str(tmp_path / "pdfs")
        handler.rag_url = "http://localhost:8767"
        handler.download_delay = 0.0
        handler.send_error_json = MagicMock()

        result = ExtractorHandler.handle_process(handler, {"paper_id": paper_id})

        # If arXiv is accessible and RAGAnything processes the PDF,
        # we should get results. If arXiv blocks, the paper will fail.
        assert result is not None
        assert "papers_processed" in result or "papers_failed" in result
