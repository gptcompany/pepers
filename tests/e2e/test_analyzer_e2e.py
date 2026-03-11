"""End-to-end tests for Analyzer service — real LLM calls via fallback chain.

These tests make real LLM calls using the configured fallback chain.
They are skipped if no LLM provider is available.

Run with: pytest tests/e2e/test_analyzer_e2e.py -m e2e -v
"""

from __future__ import annotations

import json

import pytest

from shared.db import init_db, transaction
from shared.llm import fallback_chain
from services.analyzer.main import AnalyzerHandler, migrate_db
from services.analyzer.prompt import (
    EXPECTED_SCORE_KEYS,
    PROMPT_VERSION,
    SCORING_SYSTEM_PROMPT,
    build_scoring_system_prompt,
    format_scoring_prompt,
)
from services.discovery.main import upsert_paper

pytestmark = pytest.mark.e2e


def _llm_available() -> bool:
    """Check if at least one LLM provider is reachable."""
    try:
        fallback_chain("Say OK", "Reply with just OK")
        return True
    except RuntimeError:
        return False


@pytest.fixture
def e2e_db(tmp_path):
    """Temporary SQLite database for E2E tests with migration applied."""
    db_path = tmp_path / "e2e_analyzer.db"
    init_db(db_path)
    migrate_db(str(db_path))
    return str(db_path)


class TestAnalyzerE2E:
    """End-to-end tests with real LLM calls."""

    def test_scores_paper(self):
        """Call real LLM with a paper prompt and validate JSON structure."""
        if not _llm_available():
            pytest.skip("No LLM provider available")

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

        response_text, provider = fallback_chain(prompt, SCORING_SYSTEM_PROMPT)
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
        """Insert a paper, analyze with real LLM, verify DB update."""
        if not _llm_available():
            pytest.skip("No LLM provider available")

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

        from unittest.mock import MagicMock
        handler = MagicMock(spec=AnalyzerHandler)
        handler.db_path = e2e_db
        handler.threshold = 0.7
        handler.max_papers_default = 10
        handler.send_error_json = MagicMock()

        result = AnalyzerHandler.handle_process(handler, {"paper_id": paper_id})
        assert result["papers_analyzed"] == 1
        assert result["llm_provider"] is not None

        with transaction(e2e_db) as conn:
            row = conn.execute(
                "SELECT stage, score, prompt_version FROM papers WHERE id=?",
                (paper_id,),
            ).fetchone()
        assert row["stage"] in ("analyzed", "rejected")
        assert row["score"] is not None
        assert 0.0 <= row["score"] <= 1.0
        assert row["prompt_version"] == PROMPT_VERSION

    def test_rejected_paper_not_kelly(self, e2e_db):
        """A clearly non-Kelly paper should be rejected or scored low."""
        if not _llm_available():
            pytest.skip("No LLM provider available")

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
        assert row["score"] < 0.7 or row["stage"] == "rejected"


class TestAnalyzerTopicAgnostic:
    """E2E tests verifying topic_relevance adapts to different research topics."""

    def test_custom_topic_scores_relevant_paper(self, e2e_db, monkeypatch):
        """With RP_ANALYZER_TOPIC='reinforcement learning', an RL paper
        should score high on topic_relevance."""
        if not _llm_available():
            pytest.skip("No LLM provider available")

        monkeypatch.setenv(
            "RP_ANALYZER_TOPIC",
            "reinforcement learning, policy gradient, Q-learning, multi-agent RL",
        )
        custom_prompt = build_scoring_system_prompt(
            "reinforcement learning, policy gradient, Q-learning, multi-agent RL"
        )
        assert "reinforcement learning" in custom_prompt

        user_prompt = format_scoring_prompt(
            title="Multi-Agent Reinforcement Learning for Cooperative Navigation",
            abstract=(
                "We propose a multi-agent reinforcement learning framework for "
                "cooperative navigation tasks. Using policy gradient methods with "
                "centralized training and decentralized execution, our approach "
                "achieves state-of-the-art results on several MARL benchmarks."
            ),
            authors=["RL Researcher"],
            categories=["cs.AI", "cs.MA"],
        )
        response, provider = fallback_chain(user_prompt, custom_prompt)
        data = json.loads(response)

        assert set(data["scores"].keys()) == EXPECTED_SCORE_KEYS
        assert float(data["scores"]["topic_relevance"]) >= 0.5

    def test_custom_topic_rejects_unrelated_paper(self, e2e_db, monkeypatch):
        """With RP_ANALYZER_TOPIC='quantum computing', a finance paper
        should score low on topic_relevance."""
        if not _llm_available():
            pytest.skip("No LLM provider available")

        custom_prompt = build_scoring_system_prompt(
            "quantum computing, quantum error correction, qubit architectures"
        )
        assert "quantum computing" in custom_prompt

        user_prompt = format_scoring_prompt(
            title="The Kelly Criterion in Sports Betting",
            abstract=(
                "We study the application of the Kelly criterion to sequential "
                "sports betting decisions with correlated outcomes and discuss "
                "practical bankroll management strategies."
            ),
            authors=["Finance Author"],
            categories=["q-fin.PM"],
        )
        response, provider = fallback_chain(user_prompt, custom_prompt)
        data = json.loads(response)

        assert set(data["scores"].keys()) == EXPECTED_SCORE_KEYS
        assert float(data["scores"]["topic_relevance"]) < 0.5

    def test_default_prompt_is_neutral_when_topic_missing(self):
        """Without an explicit topic, analyzer prompt must remain domain-neutral."""
        from services.analyzer.prompt import SCORING_SYSTEM_PROMPT
        assert "No explicit run topic was provided" in SCORING_SYSTEM_PROMPT
        assert "Do not assume any hidden default domain" in SCORING_SYSTEM_PROMPT
