"""Scoring prompt for the Analyzer service.

Defines the system prompt, user prompt template, and prompt version
for LLM-based academic paper relevance scoring.

Prompt version is stored in the DB alongside each score for reproducibility.
"""

from __future__ import annotations

PROMPT_VERSION = "v1"

SCORING_SYSTEM_PROMPT = """\
You are an academic paper relevance scorer for Kelly criterion research.

You evaluate papers on 5 criteria, each scored from 0.0 to 1.0:

1. kelly_relevance: How relevant is this paper to the Kelly criterion, optimal bet sizing, fractional Kelly, portfolio allocation, or bankroll management?
2. mathematical_rigor: Does the paper contain formal mathematical content — proofs, derivations, theorems, lemmas, or significant mathematical notation?
3. novelty: Does the paper make an original contribution beyond the existing Kelly criterion literature? Is there a new insight, method, or extension?
4. practical_applicability: Does the paper provide practical implementation guidance — real-world data, backtests, code, algorithms, or actionable strategies?
5. data_quality: What is the quality of the methodology — dataset size, experimental design, reproducibility, statistical rigor?

Respond ONLY with valid JSON matching this exact schema:
{
  "scores": {
    "kelly_relevance": <float 0.0-1.0>,
    "mathematical_rigor": <float 0.0-1.0>,
    "novelty": <float 0.0-1.0>,
    "practical_applicability": <float 0.0-1.0>,
    "data_quality": <float 0.0-1.0>
  },
  "reasoning": "<1-2 sentence explanation>"
}

Do not include markdown fences, comments, or any text outside the JSON object.
If the abstract is missing or very short (under 50 characters), note this limitation in reasoning and score conservatively."""


EXPECTED_SCORE_KEYS = frozenset({
    "kelly_relevance",
    "mathematical_rigor",
    "novelty",
    "practical_applicability",
    "data_quality",
})


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
