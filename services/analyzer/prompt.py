"""Scoring prompt for the Analyzer service.

Defines the system prompt, user prompt template, and prompt version
for LLM-based academic paper relevance scoring.

Prompt version is stored in the DB alongside each score for reproducibility.

The scoring criteria are topic-agnostic: `topic_relevance` adapts to
whatever research topic is configured via RP_ANALYZER_TOPIC env var.
"""

from __future__ import annotations

import os

PROMPT_VERSION = "v2"

# Research topic — configurable via env var, defaults to Kelly criterion
DEFAULT_TOPIC = "Kelly criterion, optimal bet sizing, fractional Kelly, portfolio allocation, or bankroll management"
ANALYZER_TOPIC = os.environ.get("RP_ANALYZER_TOPIC", DEFAULT_TOPIC)

EXPECTED_SCORE_KEYS = frozenset({
    "topic_relevance",
    "mathematical_rigor",
    "novelty",
    "practical_applicability",
    "data_quality",
})


def build_scoring_system_prompt(topic: str | None = None) -> str:
    """Build the system prompt with topic-specific relevance criterion.

    Args:
        topic: Research topic description. Uses RP_ANALYZER_TOPIC env var
            if None, falls back to DEFAULT_TOPIC.

    Returns:
        Complete system prompt string.
    """
    if topic is None:
        topic = ANALYZER_TOPIC

    return f"""\
You are an academic paper relevance scorer for research.

You evaluate papers on 5 criteria, each scored from 0.0 to 1.0:

1. topic_relevance: How relevant is this paper to the following research topic? "{topic}"
2. mathematical_rigor: Does the paper contain formal mathematical content — proofs, derivations, theorems, lemmas, or significant mathematical notation?
3. novelty: Does the paper make an original contribution beyond the existing literature on this topic? Is there a new insight, method, or extension?
4. practical_applicability: Does the paper provide practical implementation guidance — real-world data, backtests, code, algorithms, or actionable strategies?
5. data_quality: What is the quality of the methodology — dataset size, experimental design, reproducibility, statistical rigor?

Respond ONLY with valid JSON matching this exact schema:
{{
  "scores": {{
    "topic_relevance": <float 0.0-1.0>,
    "mathematical_rigor": <float 0.0-1.0>,
    "novelty": <float 0.0-1.0>,
    "practical_applicability": <float 0.0-1.0>,
    "data_quality": <float 0.0-1.0>
  }},
  "reasoning": "<1-2 sentence explanation>"
}}

Do not include markdown fences, comments, or any text outside the JSON object.
If the abstract is missing or very short (under 50 characters), note this limitation in reasoning and score conservatively."""


# Default instance for backward compatibility
SCORING_SYSTEM_PROMPT = build_scoring_system_prompt()


def format_scoring_prompt(
    title: str,
    abstract: str | None,
    authors: list[str],
    categories: list[str],
) -> str:
    """Build the user prompt for LLM paper scoring.

    Args:
        title: Paper title.
        abstract: Paper abstract (may be None or short).
        authors: List of author names.
        categories: List of arXiv categories.

    Returns:
        Formatted user prompt string.
    """
    authors_str = ", ".join(authors[:5])
    if len(authors) > 5:
        authors_str += f" et al. ({len(authors)} total)"
    categories_str = ", ".join(categories)

    abstract_text = (
        abstract if abstract and len(abstract) >= 50 else "(abstract not available)"
    )

    return (
        f"Score this academic paper:\n\n"
        f"Title: {title}\n"
        f"Authors: {authors_str}\n"
        f"Categories: {categories_str}\n\n"
        f"Abstract:\n{abstract_text}"
    )
