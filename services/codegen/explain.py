"""LLM explanation module for the Codegen service.

Generates plain-language explanations of validated formulas
using Ollama (primary) with Gemini fallback.

Uses structured output (JSON schema) for Ollama to ensure
consistent response format.
"""

from __future__ import annotations

import logging

from shared.config import LLM_SEED, LLM_TEMPERATURE
from shared.llm import call_ollama, fallback_chain
from shared.models import FormulaExplanation

logger = logging.getLogger(__name__)

EXPLANATION_SYSTEM_PROMPT = """You are a mathematical finance expert who explains formulas to practitioners.
Given a LaTeX formula and its surrounding context from an academic paper,
produce a plain-language explanation.

Rules:
1. Explain what the formula COMPUTES (purpose), not how to derive it
2. Define every variable/symbol used
3. State the key assumptions the formula requires
4. Use concrete financial examples when possible
5. Keep the explanation accessible to someone with undergraduate math

Respond ONLY with valid JSON matching this schema:
{
  "explanation": "<2-4 sentence plain-language explanation>",
  "variables": [{"symbol": "...", "name": "...", "description": "..."}],
  "assumptions": ["..."],
  "domain": "<mathematical finance | probability | optimization | statistics>"
}"""

CODEGEN_FALLBACK_ORDER = ["ollama", "openrouter", "gemini_cli"]


def explain_formula(
    latex: str,
    context: str | None,
    paper_title: str | None,
) -> dict | None:
    """Generate plain-language explanation of a formula via LLM.

    Tries Ollama first with structured output (JSON schema enforcement),
    then falls back to Gemini SDK/CLI.

    Args:
        latex: LaTeX formula string.
        context: Surrounding text from the paper (up to 200 chars).
        paper_title: Title of the source paper.

    Returns:
        FormulaExplanation dict or None on failure.
    """
    user_prompt = f"Formula: {latex}"
    if context:
        user_prompt += f"\nContext: {context}"
    if paper_title:
        user_prompt += f"\nPaper: {paper_title}"
    user_prompt += " /no_think"

    # Try Ollama first with structured output
    try:
        result = call_ollama(
            prompt=user_prompt,
            system=EXPLANATION_SYSTEM_PROMPT,
            format=FormulaExplanation.model_json_schema(),
            options={"temperature": LLM_TEMPERATURE, "seed": LLM_SEED, "num_predict": 4096, "num_ctx": 4096},
        )
        return FormulaExplanation.model_validate_json(result).model_dump()
    except Exception as e:
        logger.warning("Ollama explanation failed: %s", e)

    # Fallback to Gemini
    try:
        result, provider = fallback_chain(
            prompt=user_prompt,
            system=EXPLANATION_SYSTEM_PROMPT,
            order=["openrouter", "gemini_cli"],
        )
        return FormulaExplanation.model_validate_json(result).model_dump()
    except Exception as e:
        logger.warning("All LLM explanation providers failed: %s", e)
        return None
