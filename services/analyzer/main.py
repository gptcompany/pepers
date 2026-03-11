"""Analyzer service — LLM-based relevance scoring for discovered papers.

Second microservice in the research pipeline. Reads papers with stage='discovered',
scores them on 5 criteria via LLM (Gemini CLI → SDK → Ollama fallback), and updates
the DB with scores and stage ('analyzed' or 'rejected' based on threshold).

Usage:
    python -m services.analyzer.main

Environment:
    RP_ANALYZER_PORT=8771            # Service port (default: 8771)
    RP_ANALYZER_THRESHOLD=0.7        # Score threshold (default: 0.7)
    RP_ANALYZER_MAX_PAPERS=10        # Default batch size (default: 10)
    RP_ANALYZER_GEMINI_MODEL=gemini-1.5-flash  # Gemini model
    RP_ANALYZER_OLLAMA_URL=http://localhost:11434  # Ollama endpoint
    RP_ANALYZER_OLLAMA_MODEL=qwen3:8b  # Ollama model
    GEMINI_API_KEY=...               # Gemini API key (from SSOT via dotenvx)
    RP_DB_PATH=data/research.db      # SQLite database path
    RP_LOG_LEVEL=INFO                # Log level
"""

from __future__ import annotations

import json
import logging
import os
import re
import time

from shared.config import load_config
from shared.db import init_db, transaction
from shared.server import BaseHandler, BaseService, route

from services.analyzer.llm import fallback_chain
from services.analyzer.prompt import (
    EXPECTED_SCORE_KEYS,
    PROMPT_VERSION,
    SCORING_SYSTEM_PROMPT,
    build_scoring_system_prompt,
    format_scoring_prompt,
)

logger = logging.getLogger(__name__)


DEFAULT_ANALYZER_FALLBACK_ORDER = [
    "gemini_cli",
    "gemini_sdk",
    "openrouter",
    "ollama",
]


def _analyzer_fallback_order() -> list[str]:
    """Prefer fast Gemini/OpenRouter providers before local heavy fallbacks."""
    raw = os.environ.get("RP_ANALYZER_LLM_FALLBACK_ORDER", "")
    order = [item.strip() for item in raw.split(",") if item.strip()]
    return order or list(DEFAULT_ANALYZER_FALLBACK_ORDER)


def migrate_db(db_path: str) -> None:
    """Add prompt_version column if missing. Idempotent."""
    with transaction(db_path) as conn:
        cursor = conn.execute("PRAGMA table_info(papers)")
        columns = {row[1] for row in cursor.fetchall()}
        if "prompt_version" not in columns:
            conn.execute("ALTER TABLE papers ADD COLUMN prompt_version TEXT")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_papers_prompt_version "
                "ON papers(prompt_version)"
            )
            logger.info("Migration: added prompt_version column to papers")


class AnalyzerHandler(BaseHandler):
    """Handler for the Analyzer service.

    Endpoints:
        POST /process — Analyze discovered papers with LLM scoring.
    """

    threshold: float = 0.7
    max_papers_default: int = 10
    request_budget_seconds: int = 900

    @route("POST", "/process")
    def handle_process(self, data: dict) -> dict:
        """Analyze discovered papers with LLM scoring.

        Request body:
            {
                "paper_id": 42,        # Optional: analyze specific paper
                "topic": "limit order book microstructure",  # Optional topic override
                "max_papers": 10,      # Optional: batch limit (default 10)
                "force": false         # Optional: reprocess already scored papers
            }

        Returns:
            Summary dict with counts and scoring details.
        """
        start = time.time()

        # Parse request
        paper_id = data.get("paper_id")
        topic = data.get("topic")
        max_papers: int = data.get("max_papers", self.max_papers_default)
        force = data.get("force", False)

        if max_papers is not None and (
            not isinstance(max_papers, int) or max_papers < 1 or max_papers > 100
        ):
            self.send_error_json(
                "'max_papers' must be integer 1-100", "VALIDATION_ERROR", 422
            )
            return None  # type: ignore[return-value]
        if topic is not None and not isinstance(topic, str):
            self.send_error_json(
                "'topic' must be a string", "VALIDATION_ERROR", 422
            )
            return None  # type: ignore[return-value]
        system_prompt = (
            build_scoring_system_prompt(topic.strip())
            if isinstance(topic, str) and topic.strip()
            else SCORING_SYSTEM_PROMPT
        )

        assert self.db_path is not None, "db_path must be set"
        db_path: str = self.db_path

        # Query papers
        papers = _query_papers(db_path, paper_id, max_papers, force)
        if not papers:
            elapsed_ms = int((time.time() - start) * 1000)
            return {
                "papers_analyzed": 0,
                "papers_accepted": 0,
                "papers_rejected": 0,
                "avg_score": 0.0,
                "llm_provider": None,
                "prompt_version": PROMPT_VERSION,
                "errors": [],
                "time_ms": elapsed_ms,
            }

        # Process each paper
        errors: list[str] = []
        accepted = 0
        rejected = 0
        total_score = 0.0
        last_provider = None
        fallback_order = _analyzer_fallback_order()
        papers_seen = 0
        raw_request_budget = getattr(
            self,
            "request_budget_seconds",
            AnalyzerHandler.request_budget_seconds,
        )
        try:
            if isinstance(raw_request_budget, (int, float, str)):
                request_budget_seconds = int(raw_request_budget)
            else:
                raise TypeError("request budget must be numeric")
        except (TypeError, ValueError):
            request_budget_seconds = AnalyzerHandler.request_budget_seconds

        for paper in papers:
            if (
                request_budget_seconds > 0
                and papers_seen > 0
                and (time.time() - start) >= request_budget_seconds
            ):
                remaining = len(papers) - papers_seen
                msg = (
                    f"batch budget exhausted after {papers_seen} papers; "
                    f"{remaining} deferred"
                )
                logger.warning(msg)
                errors.append(msg)
                break

            pid = paper["id"]
            title = paper["title"]
            abstract = paper["abstract"]
            authors = json.loads(paper["authors"]) if paper["authors"] else []
            categories = json.loads(paper["categories"]) if paper["categories"] else []
            papers_seen += 1

            # Skip papers with no title
            if not title:
                errors.append(f"paper {pid}: missing_title")
                continue

            # Build prompt
            prompt = format_scoring_prompt(title, abstract, authors, categories)

            # Call LLM
            try:
                response_text, provider = fallback_chain(
                    prompt,
                    system_prompt,
                    order=fallback_order,
                )
                last_provider = provider
            except RuntimeError as e:
                errors.append(f"paper {pid}: {e}")
                continue

            # Parse response
            scores_data = _parse_llm_response(
                response_text,
                prompt,
                system_prompt,
                pid,
                errors,
                fallback_order=fallback_order,
            )
            if scores_data is None:
                continue

            # Validate scores
            scores = scores_data.get("scores", {})
            if set(scores.keys()) != EXPECTED_SCORE_KEYS:
                errors.append(f"paper {pid}: invalid_score_keys")
                continue

            # Clamp and validate individual scores
            clamped = False
            try:
                for key in EXPECTED_SCORE_KEYS:
                    val = float(scores[key])
                    if val < 0.0 or val > 1.0:
                        logger.warning(
                            "Score %s=%f out of range for paper %d, clamping",
                            key, val, pid,
                        )
                        scores[key] = max(0.0, min(1.0, val))
                        clamped = True
                    else:
                        scores[key] = val
            except (ValueError, TypeError) as e:
                errors.append(f"paper {pid}: invalid_score_value: {e}")
                continue

            # Compute overall
            overall = sum(scores.values()) / len(EXPECTED_SCORE_KEYS)
            total_score += overall

            # Determine stage
            new_stage = "analyzed" if overall >= self.threshold else "rejected"
            if new_stage == "analyzed":
                accepted += 1
            else:
                rejected += 1

            # Update DB
            _update_paper_score(
                db_path, pid, new_stage, overall, clamped, errors
            )

        elapsed_ms = int((time.time() - start) * 1000)
        analyzed_count = accepted + rejected
        avg_score = total_score / analyzed_count if analyzed_count > 0 else 0.0

        logger.info(
            "Analysis complete: analyzed=%d accepted=%d rejected=%d "
            "avg_score=%.2f provider=%s time=%dms",
            analyzed_count, accepted, rejected, avg_score,
            last_provider, elapsed_ms,
        )

        return {
            "papers_analyzed": analyzed_count,
            "papers_accepted": accepted,
            "papers_rejected": rejected,
            "avg_score": round(avg_score, 4),
            "llm_provider": last_provider,
            "prompt_version": PROMPT_VERSION,
            "errors": errors,
            "time_ms": elapsed_ms,
        }


def _query_papers(
    db_path: str,
    paper_id: int | None,
    max_papers: int,
    force: bool,
) -> list:
    """Query papers to analyze from the database."""
    with transaction(db_path) as conn:
        if paper_id is not None:
            if force:
                cursor = conn.execute(
                    "SELECT * FROM papers WHERE id=? "
                    "AND stage IN ('discovered', 'analyzed', 'rejected')",
                    (paper_id,),
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM papers WHERE id=? AND stage='discovered'",
                    (paper_id,),
                )
        else:
            cursor = conn.execute(
                "SELECT * FROM papers WHERE stage='discovered' "
                "ORDER BY created_at ASC LIMIT ?",
                (max_papers,),
            )
        return [dict(row) for row in cursor.fetchall()]


def _clean_json_text(text: str) -> str:
    """Clean common LLM JSON quirks before parsing."""
    text = text.strip().lstrip("\ufeff")
    # trailing commas: ,} or ,]
    text = re.sub(r",\s*([}\]])", r"\1", text)
    # single-line comments
    text = re.sub(r"//[^\n]*", "", text)
    return text


def _parse_llm_response(
    response_text: str,
    prompt: str,
    system_prompt: str,
    paper_id: int,
    errors: list[str],
    *,
    fallback_order: list[str] | None = None,
) -> dict | None:
    """Parse LLM JSON response, retry once on failure."""
    try:
        return json.loads(_clean_json_text(response_text))
    except json.JSONDecodeError:
        logger.warning("Invalid JSON from LLM for paper %d, retrying", paper_id)

    # Retry with stricter suffix
    retry_prompt = (
        prompt
        + "\n\nRespond ONLY with valid JSON, no markdown fences, no extra text."
    )
    try:
        response_text, _ = fallback_chain(
            retry_prompt,
            system_prompt,
            order=fallback_order,
        )
        return json.loads(_clean_json_text(response_text))
    except (json.JSONDecodeError, RuntimeError) as e:
        errors.append(f"paper {paper_id}: invalid JSON after retry: {e}")
        return None


def _update_paper_score(
    db_path: str,
    paper_id: int,
    stage: str,
    score: float,
    clamped: bool,
    errors: list[str],
) -> None:
    """Update paper with analysis results."""
    error_value = "score_clamped" if clamped else None
    try:
        with transaction(db_path) as conn:
            conn.execute(
                "UPDATE papers SET stage=?, score=?, prompt_version=?, "
                "error=?, updated_at=datetime('now') WHERE id=?",
                (stage, score, PROMPT_VERSION, error_value, paper_id),
            )
    except Exception as e:
        errors.append(f"paper {paper_id}: DB update failed: {e}")
        logger.error("Failed to update paper %d: %s", paper_id, e)


def main() -> None:
    """Start the Analyzer service."""
    config = load_config("analyzer")
    init_db(config.db_path)
    migrate_db(str(config.db_path))

    # Load analyzer-specific config
    AnalyzerHandler.threshold = float(
        os.environ.get("RP_ANALYZER_THRESHOLD", "0.7")
    )
    AnalyzerHandler.max_papers_default = int(
        os.environ.get("RP_ANALYZER_MAX_PAPERS", "10")
    )
    AnalyzerHandler.request_budget_seconds = int(
        os.environ.get("RP_ANALYZER_REQUEST_BUDGET_SECONDS", "900")
    )

    service = BaseService(
        "analyzer", config.port, AnalyzerHandler, str(config.db_path)
    )
    service.run()


if __name__ == "__main__":
    main()
