"""Extractor service — PDF download + RAGAnything + LaTeX formula extraction.

Third microservice in the research pipeline. Reads papers with stage='analyzed',
downloads PDFs from arXiv, sends to RAGAnything for text extraction, parses LaTeX
formulas via regex, and stores results in the formulas table.

Usage:
    python -m services.extractor.main

Environment:
    RP_EXTRACTOR_PORT=8772                    # Service port (default: 8772)
    RP_EXTRACTOR_MAX_PAPERS=10                # Default batch size
    RP_EXTRACTOR_PDF_DIR=data/pdfs            # PDF storage directory
    RP_EXTRACTOR_DOWNLOAD_DELAY=3.0           # Seconds between arXiv downloads
    RP_EXTRACTOR_RAG_URL=http://localhost:8767 # RAGAnything base URL
    RP_DB_PATH=data/research.db               # SQLite database path
    RP_LOG_LEVEL=INFO                         # Log level
"""

from __future__ import annotations

import http.client
import logging
import os
import re
import time
import urllib.error
from pathlib import Path

import requests

from shared.rag import normalize_rag_force_parser
from shared.config import load_config, resolve_localhost_url
from shared.db import get_connection, init_db, transaction
from shared.models import Formula, Paper
from shared.server import BaseHandler, BaseService, route

from services.extractor import latex, pdf, rag_client

logger = logging.getLogger(__name__)
_RETRYABLE_HTTP_STATUS = {408, 429, 500, 502, 503, 504}
_RETRYABLE_COOLDOWN_SECONDS = 300
_RETRYABLE_ERROR_PATTERNS = (
    re.compile(r"\bread timed out\b"),
    re.compile(r"\bconnect(?:ion)? timed out\b"),
    re.compile(r"\bconnection reset by peer\b"),
    re.compile(r"\bconnection aborted\b"),
    re.compile(r"\bremote disconnected\b"),
    re.compile(r"\bremote end closed connection without response\b"),
    re.compile(r"\btemporarily unavailable\b"),
)


def _check_consistency(db_path: str) -> None:
    """Detect papers at stage 'extracted' with 0 formulas (possible failed extraction)."""
    try:
        conn = get_connection(db_path)
        try:
            stuck = conn.execute(
                "SELECT p.id, p.arxiv_id FROM papers p "
                "WHERE p.stage = 'extracted' "
                "AND NOT EXISTS (SELECT 1 FROM formulas f WHERE f.paper_id = p.id)"
            ).fetchall()
            if stuck:
                logger.warning(
                    "Consistency: %d papers at stage 'extracted' with 0 formulas: %s",
                    len(stuck), [row[1] for row in stuck],
                )
        finally:
            conn.close()
    except Exception:
        logger.exception("Consistency check failed")


def _load_notations(db_path: str) -> list[dict]:
    """Load custom notations from database."""
    try:
        conn = get_connection(db_path)
        try:
            rows = conn.execute(
                "SELECT name, body, nargs FROM custom_notations"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
    except Exception:
        return []


def _build_extraction_paper_id(paper: Paper) -> str:
    """Build a stable document identifier for RAG processing."""
    if paper.arxiv_id:
        return f"arxiv:{paper.arxiv_id}"
    if paper.id is not None:
        return f"paper:{paper.id}"
    if paper.doi:
        return f"doi:{paper.doi}"
    raise ValueError("cannot build extraction document id")


def _retryable_cooldown_seconds() -> int:
    return max(
        0,
        int(
            os.environ.get(
                "RP_EXTRACTOR_RETRYABLE_COOLDOWN",
                str(_RETRYABLE_COOLDOWN_SECONDS),
            )
        ),
    )


def _retryable_error_message(message: str) -> bool:
    normalized = message.strip().lower()
    if normalized in {"timed out", "timeout"}:
        return True
    return any(pattern.search(normalized) for pattern in _RETRYABLE_ERROR_PATTERNS)


def _is_retryable_extraction_error(exc: BaseException) -> bool:
    """Return True when the extractor failure looks transient/retryable."""
    if isinstance(exc, requests.HTTPError):
        status = getattr(getattr(exc, "response", None), "status_code", None)
        return status in _RETRYABLE_HTTP_STATUS
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in _RETRYABLE_HTTP_STATUS
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    if isinstance(
        exc,
        (
            TimeoutError,
            urllib.error.URLError,
            ConnectionError,
            ConnectionResetError,
            http.client.HTTPException,
        ),
    ):
        return True
    return _retryable_error_message(str(exc))


class ExtractorHandler(BaseHandler):
    """Handler for the Extractor service.

    Endpoints:
        POST /process — Extract formulas from analyzed papers.
    """

    max_papers_default: int = 10
    pdf_dir: str = "data/pdfs"
    rag_url: str = "http://localhost:8767"
    rag_force_parser: str | None = None
    download_delay: float = 3.0

    @route("POST", "/process")
    def handle_process(self, data: dict) -> dict | None:
        """Extract formulas from analyzed papers.

        Request body:
            {
                "paper_id": 42,        # Optional: process specific paper
                "max_papers": 10,      # Optional: batch limit (default 10)
                "force_parser": "docling",  # Optional: override RAG parser
                "force": false         # Optional: reprocess extracted/failed papers
            }

        Returns:
            Summary dict with counts and error details.
        """
        start = time.time()

        paper_id = data.get("paper_id")
        max_papers: int = data.get("max_papers", self.max_papers_default)
        force = data.get("force", False)
        force_parser = self.rag_force_parser
        if "force_parser" in data:
            try:
                force_parser = normalize_rag_force_parser(data.get("force_parser"))
            except ValueError as exc:
                self.send_error_json(str(exc), "VALIDATION_ERROR", 400)
                return None

        assert self.db_path is not None, "db_path must be set"
        db_path: str = self.db_path

        papers = _query_papers(db_path, paper_id, max_papers, force)
        if not papers:
            return {
                "success": True,
                "service": "extractor",
                "papers_processed": 0,
                "formulas_extracted": 0,
                "errors": [],
                "time_ms": int((time.time() - start) * 1000),
            }

        # Check RAGAnything before starting batch
        try:
            rag_client.check_service(self.rag_url)
        except Exception as e:
            self.send_error_json(str(e), "SERVICE_UNAVAILABLE", 503)
            return None
        try:
            rag_client.validate_path_config()
        except RuntimeError as e:
            self.send_error_json(str(e), "CONFIG_ERROR", 503)
            return None

        session = pdf.create_session()
        errors: list[str] = []
        total_formulas = 0
        papers_ok = 0
        papers_deferred = 0

        for i, paper_row in enumerate(papers):
            pid = paper_row["id"]
            paper = Paper(**paper_row)

            try:
                if not pdf.has_download_source(paper):
                    raise ValueError(
                        "no downloadable PDF source (missing arxiv_id and pdf_url)"
                    )

                # Step 1: Download PDF
                pdf_path = pdf.download_pdf(
                    paper, Path(self.pdf_dir), session
                )

                # Step 2: RAGAnything processing
                markdown = rag_client.process_paper(
                    pdf_path,
                    _build_extraction_paper_id(paper),
                    self.rag_url,
                    force_parser=force_parser,
                    force_reprocess=force or force_parser is not None,
                )

                # Step 3: Extract formulas
                raw = latex.extract_formulas(markdown)
                filtered = latex.filter_formulas(raw)

                # Step 3b: Expand custom notations
                notations = _load_notations(db_path)
                if notations:
                    filtered = latex.expand_custom_notations(filtered, notations)

                formulas = latex.formulas_to_models(pid, markdown, filtered)

                # Step 4: Store formulas + update paper
                _store_results(db_path, pid, formulas)
                total_formulas += len(formulas)
                papers_ok += 1

                logger.info(
                    "Paper %d: %d formulas extracted (%d raw, %d filtered)",
                    pid, len(formulas), len(raw), len(filtered),
                )

            except Exception as e:
                logger.error("Failed paper %d: %s", pid, e)
                errors.append(f"paper {pid}: {e}")
                if _is_retryable_extraction_error(e):
                    papers_deferred += 1
                    _mark_retryable(db_path, pid, str(e))
                else:
                    _mark_failed(db_path, pid, str(e))

            # Rate limit between papers
            if i < len(papers) - 1:
                time.sleep(self.download_delay)

        elapsed_ms = int((time.time() - start) * 1000)

        logger.info(
            "Extraction complete: processed=%d formulas=%d errors=%d time=%dms",
            papers_ok, total_formulas, len(errors), elapsed_ms,
        )

        return {
            "success": papers_ok > 0 or not errors,
            "service": "extractor",
            "papers_processed": papers_ok,
            "formulas_extracted": total_formulas,
            "papers_failed": len(errors) - papers_deferred,
            "papers_deferred": papers_deferred,
            "errors": errors,
            "time_ms": elapsed_ms,
        }


def _query_papers(
    db_path: str,
    paper_id: int | None,
    max_papers: int,
    force: bool,
) -> list:
    """Query papers ready for extraction.

    Batch mode filters out rows with no downloadable source so extractor does not
    spend its budget on papers that can only fail with `pdf/None`.
    """
    retryable_clause = (
        "(error IS NULL OR error NOT LIKE 'extractor retryable:%' "
        "OR datetime(updated_at) <= datetime('now', ?))"
    )
    retryable_backoff = f"-{_retryable_cooldown_seconds()} seconds"
    with transaction(db_path) as conn:
        if paper_id is not None:
            if force:
                cursor = conn.execute(
                    "SELECT * FROM papers WHERE id=? "
                    "AND stage IN ('analyzed', 'extracted', 'failed')",
                    (paper_id,),
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM papers WHERE id=? AND stage='analyzed'",
                    (paper_id,),
                )
        else:
            cursor = conn.execute(
                "SELECT * FROM papers WHERE stage='analyzed' "
                f"AND {retryable_clause} "
                "AND (NULLIF(TRIM(COALESCE(arxiv_id, '')), '') IS NOT NULL "
                "OR NULLIF(TRIM(COALESCE(pdf_url, '')), '') IS NOT NULL) "
                "ORDER BY created_at ASC LIMIT ?",
                (retryable_backoff, max_papers),
            )
        return [dict(row) for row in cursor.fetchall()]


def _store_results(db_path: str, paper_id: int, formulas: list[Formula]) -> None:
    """Insert formulas and update paper stage."""
    with transaction(db_path) as conn:
        for f in formulas:
            existing = conn.execute(
                "SELECT id FROM formulas WHERE paper_id=? AND latex_hash=?",
                (paper_id, f.latex_hash),
            ).fetchone()
            if existing:
                continue

            conn.execute(
                "INSERT INTO formulas (paper_id, latex, latex_hash, "
                "description, formula_type, context, stage, error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f.paper_id, f.latex, f.latex_hash,
                    f.description, f.formula_type, f.context,
                    f.stage.value, f.error,
                ),
            )

        conn.execute(
            "UPDATE papers SET stage='extracted', error=NULL, updated_at=datetime('now') "
            "WHERE id=?",
            (paper_id,),
        )


def _mark_retryable(db_path: str, paper_id: int, error: str) -> None:
    """Keep paper retryable when extractor failed for a transient reason."""
    with transaction(db_path) as conn:
        conn.execute(
            "UPDATE papers SET stage='analyzed', error=?, "
            "updated_at=datetime('now') WHERE id=?",
            (f"extractor retryable: {error}", paper_id),
        )


def _mark_failed(db_path: str, paper_id: int, error: str) -> None:
    """Mark paper as failed with error message."""
    with transaction(db_path) as conn:
        conn.execute(
            "UPDATE papers SET stage='failed', error=?, "
            "updated_at=datetime('now') WHERE id=?",
            (f"extractor: {error}", paper_id),
        )


def main() -> None:
    """Start the Extractor service."""
    config = load_config("extractor")
    init_db(config.db_path)
    _check_consistency(str(config.db_path))

    ExtractorHandler.max_papers_default = int(
        os.environ.get("RP_EXTRACTOR_MAX_PAPERS", "10")
    )
    ExtractorHandler.pdf_dir = os.environ.get("RP_EXTRACTOR_PDF_DIR", "data/pdfs")
    ExtractorHandler.rag_url = resolve_localhost_url(
        os.environ.get("RP_EXTRACTOR_RAG_URL", "http://localhost:8767")
    )
    try:
        ExtractorHandler.rag_force_parser = normalize_rag_force_parser(
            os.environ.get("RP_EXTRACTOR_RAG_FORCE_PARSER")
        )
    except ValueError as exc:
        logger.warning(
            "Ignoring invalid RP_EXTRACTOR_RAG_FORCE_PARSER: %s",
            exc,
        )
        ExtractorHandler.rag_force_parser = None
    ExtractorHandler.download_delay = float(
        os.environ.get("RP_EXTRACTOR_DOWNLOAD_DELAY", "3.0")
    )

    service = BaseService(
        "extractor", config.port, ExtractorHandler, str(config.db_path)
    )
    service.run()


if __name__ == "__main__":
    main()
