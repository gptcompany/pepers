"""End-to-end tests for Analyzer service — real LLM calls (Ollama).

These tests make real HTTP requests to Ollama (localhost:11434).
They require Ollama running with qwen3:8b and are skipped by default.

Run with: pytest tests/e2e/test_analyzer_e2e.py -m e2e -v
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from shared.db import init_db, transaction
from services.analyzer.main import AnalyzerHandler, migrate_db
from services.analyzer.llm import call_ollama
from services.analyzer.prompt import (
    EXPECTED_SCORE_KEYS,
    SCORING_SYSTEM_PROMPT,
    format_scoring_prompt,
)
from services.discovery.main import upsert_paper

pytestmark = pytest.mark.e2e


def _ollama_available() -> bool:
    """Check if Ollama is running on localhost:11434."""
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


@pytest.fixture
def e2e_db(tmp_path):
    """Temporary SQLite database for E2E tests with migration applied."""
    db_path = tmp_path / "e2e_analyzer.db"
    init_db(db_path)
    migrate_db(str(db_path))
    return str(db_path)


class TestAnalyzerE2E:
    """End-to-end tests with real Ollama calls."""

    def test_ollama_scores_paper(self):
        """Call real Ollama with a paper prompt and validate JSON structure."""
        if not _ollama_available():
            pytest.skip("Ollama not available at localhost:11434")

        prompt = format_scoring_prompt(
            title="The Kelly Criterion in Blackjack, Sports Betting, and the Stock Market",
            abstract=(
                "We develop a general framework for applying the Kelly criterion "
                "to portfolio optimization and bet sizing across multiple assets. "
                "The paper provides closed-form solutions for fractional Kelly "
                "strategies and demonstrates their application to real-world data."
            ),
            authors=["Edward O. Thorp"],
            categories=["q-fin.PM", "math.PR"],
        )

        response_text = call_ollama(prompt, SCORING_SYSTEM_PROMPT)
        data = json.loads(response_text)

        assert "scores" in data
        scores = data["scores"]
        assert set(scores.keys()) == EXPECTED_SCORE_KEYS

        for key, val in scores.items():
            fval = float(val)
            assert 0.0 <= fval <= 1.0, f"{key}={fval} out of range"

        # For a highly relevant paper, topic_relevance should be high
        assert float(scores["topic_relevance"]) >= 0.5

    def test_full_pipeline_discover_then_analyze(self, e2e_db):
        """Insert a paper, analyze with real Ollama, verify DB update."""
        if not _ollama_available():
            pytest.skip("Ollama not available at localhost:11434")

        # Insert paper
        paper = {
            "arxiv_id": "2401.00001",
            "title": "Optimal Kelly Betting with Continuous Rebalancing",
            "abstract": (
                "This paper derives optimal betting fractions using the Kelly criterion "
                "for a portfolio of correlated assets with continuous rebalancing. "
                "We prove convergence of the discrete-time strategy to the continuous limit."
            ),
            "authors": json.dumps(["John Kelly", "Claude Shannon"]),
            "categories": json.dumps(["q-fin.PM", "math.OC"]),
            "doi": None,
            "pdf_url": None,
            "published_date": "2024-01-15",
            "stage": "discovered",
        }
        paper_id = upsert_paper(e2e_db, paper)
        assert paper_id is not None

        # Analyze
        from unittest.mock import MagicMock
        handler = MagicMock(spec=AnalyzerHandler)
        handler.db_path = e2e_db
        handler.threshold = 0.7
        handler.max_papers_default = 10
        handler.send_error_json = MagicMock()

        result = AnalyzerHandler.handle_process(handler, {"paper_id": paper_id})
        assert result["papers_analyzed"] == 1
        assert result["llm_provider"] is not None

        # Verify DB
        with transaction(e2e_db) as conn:
            row = conn.execute(
                "SELECT stage, score, prompt_version FROM papers WHERE id=?",
                (paper_id,),
            ).fetchone()
        assert row["stage"] in ("analyzed", "rejected")
        assert row["score"] is not None
        assert 0.0 <= row["score"] <= 1.0
        assert row["prompt_version"] == "v1"

    def test_rejected_paper_not_kelly(self, e2e_db):
        """A clearly non-Kelly paper should be rejected or scored low."""
        if not _ollama_available():
            pytest.skip("Ollama not available at localhost:11434")

        paper = {
            "arxiv_id": "2401.99999",
            "title": "Deep Learning for Image Classification in Medical Imaging",
            "abstract": (
                "We present a novel convolutional neural network architecture "
                "for classifying medical images including X-rays and MRI scans. "
                "Our model achieves state-of-the-art accuracy on the CheXpert dataset."
            ),
            "authors": json.dumps(["AI Researcher"]),
            "categories": json.dumps(["cs.CV", "cs.LG"]),
            "doi": None,
            "pdf_url": None,
            "published_date": "2024-06-01",
            "stage": "discovered",
        }
        paper_id = upsert_paper(e2e_db, paper)

        from unittest.mock import MagicMock
        handler = MagicMock(spec=AnalyzerHandler)
        handler.db_path = e2e_db
        handler.threshold = 0.7
        handler.max_papers_default = 10
        handler.send_error_json = MagicMock()

        result = AnalyzerHandler.handle_process(handler, {"paper_id": paper_id})
        assert result["papers_analyzed"] == 1

        with transaction(e2e_db) as conn:
            row = conn.execute(
                "SELECT stage, score FROM papers WHERE id=?", (paper_id,)
            ).fetchone()
        # Non-Kelly paper should have low score
        assert row["score"] < 0.7 or row["stage"] == "rejected"
