"""Scoring prompt for the Analyzer service.

Defines the system prompt, user prompt template, and prompt version
for LLM-based academic paper relevance scoring.

Prompt version is stored in the DB alongside each score for reproducibility.

The scoring criteria are topic-agnostic: `topic_relevance` adapts to
the topic passed by the current run. There is intentionally no global
topic default in env, because multiple concurrent jobs may target
different research areas.
"""

from __future__ import annotations

PROMPT_VERSION = "v3"
MAX_ABSTRACT_CHARS = 2000

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
        topic: Research topic description for the current run.

    Returns:
        Complete system prompt string.
    """
    normalized_topic = topic.strip() if isinstance(topic, str) else ""
    if normalized_topic:
        topic_guidance = (
            "1. topic_relevance: How relevant is this paper to the following "
            f'research topic? "{normalized_topic}"'
        )
        novelty_guidance = (
            "3. novelty: Does the paper make an original contribution beyond "
            "the existing literature on this topic? Is there a new insight, "
            "method, or extension?"
        )
    else:
        topic_guidance = (
            "1. topic_relevance: No explicit run topic was provided. Score "
            "relevance conservatively from the paper's own stated subject "
            "matter and contribution only. Do not assume any hidden default "
            "domain or previous research agenda."
        )
        novelty_guidance = (
            "3. novelty: Does the paper make an original contribution within "
            "its own stated research area? Is there a new insight, method, "
            "or extension?"
        )

    return f"""\
You score academic papers for research triage.

Score exactly these 5 criteria from 0.0 to 1.0:
{topic_guidance}
2. mathematical_rigor: Formal math content such as derivations, proofs, theorems, lemmas, or substantial notation.
{novelty_guidance}
4. practical_applicability: Implementation value such as data, code, algorithms, backtests, or actionable procedures.
5. data_quality: Methodology quality including datasets, experimental design, reproducibility, and statistics.

Return JSON only:
{{
  "scores": {{
    "topic_relevance": <float>,
    "mathematical_rigor": <float>,
    "novelty": <float>,
    "practical_applicability": <float>,
    "data_quality": <float>
  }},
  "reasoning": "<1-2 sentences>"
}}

No markdown, no comments, no extra text.
If the abstract is missing or shorter than 50 characters, mention that and score conservatively."""


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
    if abstract_text != "(abstract not available)" and len(abstract_text) > MAX_ABSTRACT_CHARS:
        abstract_text = f"{abstract_text[:MAX_ABSTRACT_CHARS].rstrip()}… [truncated]"

    return (
        f"Paper for scoring:\n\n"
        f"Title: {title}\n"
        f"Authors: {authors_str}\n"
        f"Categories: {categories_str}\n\n"
        f"Abstract:\n{abstract_text}"
    )
