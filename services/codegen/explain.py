"""LLM explanation module for the Codegen service.

Generates plain-language explanations of validated formulas
using Ollama (primary) with Gemini fallback.

Uses structured output (JSON schema) for Ollama to ensure
consistent response format.
"""

from __future__ import annotations

import json
import logging
import os

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

CODEGEN_FALLBACK_ORDER = os.environ.get(
    "RP_CODEGEN_FALLBACK_ORDER",
    os.environ.get("RP_LLM_FALLBACK_ORDER", "gemini_cli,codex_cli,claude_cli,openrouter,ollama"),
).split(",")
_BATCH_MIN, _BATCH_MAX = 5, 25
DEFAULT_BATCH_SIZE = max(_BATCH_MIN, min(_BATCH_MAX, int(
    os.environ.get("RP_CODEGEN_BATCH_SIZE", "10")
)))


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
        result, _provider = fallback_chain(
            prompt=user_prompt,
            system=EXPLANATION_SYSTEM_PROMPT,
            order=["openrouter", "gemini_cli"],
        )
        return FormulaExplanation.model_validate_json(result).model_dump()
    except Exception as e:
        logger.warning("All LLM explanation providers failed: %s", e)
        return None


BATCH_EXPLANATION_SYSTEM_PROMPT = """You are a mathematical finance expert who explains formulas to practitioners.
You will receive a numbered list of LaTeX formulas. For EACH formula, produce a JSON explanation.

Respond ONLY with a valid JSON array where each element has this schema:
{
  "index": <0-based index matching the input>,
  "explanation": "<2-4 sentence plain-language explanation>",
  "variables": [{"symbol": "...", "name": "...", "description": "..."}],
  "assumptions": ["..."],
  "domain": "<mathematical finance | probability | optimization | statistics>"
}"""


def _parse_batch_response(raw: str, formula_ids: list[int]) -> dict[int, dict]:
    """Parse batch LLM response into {formula_id: explanation_dict}.

    Args:
        raw: Raw JSON array string from LLM.
        formula_ids: Ordered list of formula IDs matching the batch prompt.

    Returns:
        Dict mapping formula_id to FormulaExplanation dict.
        Missing/invalid entries are silently skipped.
    """
    results: dict[int, dict] = {}
    try:
        items = json.loads(raw)
        if not isinstance(items, list):
            logger.warning("Batch response is not a JSON array")
            return results
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning("Batch response JSON parse failed: %s", e)
        return results

    for item in items:
        try:
            idx = item.get("index")
            if idx is None or not isinstance(idx, int):
                continue
            if idx < 0 or idx >= len(formula_ids):
                continue
            explanation = FormulaExplanation.model_validate(item).model_dump()
            results[formula_ids[idx]] = explanation
        except Exception as e:
            logger.debug("Batch item %s parse failed: %s", item.get("index"), e)
            continue

    return results


def explain_formulas_batch(
    formulas: list[dict],
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[int, dict]:
    """Generate explanations for multiple formulas in batched LLM calls.

    Chunks formulas into groups of batch_size and sends one LLM call per
    chunk, reducing total calls by ~batch_size x.

    Args:
        formulas: List of formula dicts with keys 'id', 'latex',
            'context', 'paper_title'.
        batch_size: Number of formulas per LLM call.

    Returns:
        Dict mapping formula_id to FormulaExplanation dict.
        Formulas that failed batch processing are omitted (caller proceeds
        with codegen only — no per-formula fallback).
    """
    if not formulas:
        return {}

    all_results: dict[int, dict] = {}

    for chunk_start in range(0, len(formulas), batch_size):
        chunk = formulas[chunk_start : chunk_start + batch_size]
        formula_ids = [f["id"] for f in chunk]

        # Build numbered prompt
        lines = []
        for i, f in enumerate(chunk):
            line = f"[{i}] LaTeX: {f['latex']}"
            if f.get("context"):
                line += f" | Context: {f['context']}"
            if f.get("paper_title"):
                line += f" | Paper: {f['paper_title']}"
            lines.append(line)

        batch_prompt = "\n".join(lines)

        try:
            result, _provider = fallback_chain(
                prompt=batch_prompt,
                system=BATCH_EXPLANATION_SYSTEM_PROMPT,
                order=CODEGEN_FALLBACK_ORDER,
            )
            parsed = _parse_batch_response(result, formula_ids)
            all_results.update(parsed)
            logger.info(
                "Batch explain: %d/%d formulas parsed (chunk %d-%d)",
                len(parsed), len(chunk),
                chunk_start, chunk_start + len(chunk),
            )
        except Exception as e:
            logger.warning(
                "Batch explain failed for chunk %d-%d: %s",
                chunk_start, chunk_start + len(chunk), e,
            )
            # Caller will fall back to per-formula for these

    return all_results
