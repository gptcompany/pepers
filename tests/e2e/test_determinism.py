"""Determinism calibration test — verify LLM produces identical scores.

Runs analyzer scoring 3x on the same paper data and asserts that
relevance scores are identical across runs. Requires Ollama running
with qwen3:8b model.

This is a SLOW test — not for CI. Run manually for calibration:
    pytest tests/e2e/test_determinism.py -m e2e -v
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.slow]

SAMPLE_PAPER = {
    "title": "Kelly Criterion for Optimal Portfolio Construction",
    "abstract": (
        "We apply the Kelly criterion to derive optimal bet sizing "
        "for a portfolio of correlated assets under log-normal returns. "
        "We show that the Kelly fraction generalizes to the multivariate "
        "case via quadratic programming."
    ),
    "arxiv_id": "determinism-test-001",
}


def _ollama_available() -> bool:
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _score_paper(title: str, abstract: str) -> dict:
    """Call Ollama directly with analyzer scoring prompt, return parsed scores."""
    from services.analyzer.prompt import SCORING_SYSTEM_PROMPT, format_scoring_prompt

    prompt = format_scoring_prompt(title, abstract)

    from shared.llm import call_ollama

    result = call_ollama(
        prompt=prompt,
        system=SCORING_SYSTEM_PROMPT,
        temperature=0,
    )
    return json.loads(result)


@pytest.mark.skipif(not _ollama_available(), reason="Ollama not running")
def test_analyzer_determinism_3_runs():
    """Run analyzer 3x on same paper, assert identical scores."""
    scores = []
    for i in range(3):
        result = _score_paper(SAMPLE_PAPER["title"], SAMPLE_PAPER["abstract"])
        scores.append(result)

    # All three runs should produce identical output
    assert scores[0] == scores[1], (
        f"Run 1 vs Run 2 differ:\n  Run 1: {scores[0]}\n  Run 2: {scores[1]}"
    )
    assert scores[1] == scores[2], (
        f"Run 2 vs Run 3 differ:\n  Run 2: {scores[1]}\n  Run 3: {scores[2]}"
    )
