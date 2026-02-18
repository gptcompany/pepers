"""Codegen service — LLM explanation + multi-language code generation.

Fifth microservice in the research pipeline. Reads formulas with
stage='validated', generates plain-language explanations via LLM,
produces code in C99/Rust/Python via SymPy, and stores results.

Usage:
    python -m services.codegen.main

Environment:
    RP_CODEGEN_PORT=8774                       # Service port (default: 8774)
    RP_CODEGEN_OLLAMA_URL=http://localhost:11434  # Ollama base URL
    RP_CODEGEN_MAX_FORMULAS=50                 # Default batch size
    RP_DB_PATH=data/research.db               # SQLite database path
    RP_LOG_LEVEL=INFO                         # Log level
"""

from __future__ import annotations

import json
import logging
import os
import time

from shared.config import load_config
from shared.db import get_connection, init_db, transaction
from shared.server import BaseHandler, BaseService, route

from services.codegen.explain import explain_formula, explain_formulas_batch
from services.codegen.generators import generate_all

logger = logging.getLogger(__name__)


def _check_consistency(db_path: str) -> None:
    """Detect validated formulas with partial codegen."""
    try:
        conn = get_connection(db_path)
        try:
            partial = conn.execute(
                "SELECT f.id, f.latex_hash, COUNT(g.id) as code_count "
                "FROM formulas f "
                "LEFT JOIN generated_code g ON g.formula_id = f.id "
                "WHERE f.stage = 'validated' "
                "AND g.id IS NOT NULL "
                "GROUP BY f.id"
            ).fetchall()
            if partial:
                logger.warning(
                    "Consistency: %d validated formulas have partial codegen: %s",
                    len(partial), [(row[0], row[2]) for row in partial[:10]],
                )
        finally:
            conn.close()
    except Exception:
        logger.exception("Consistency check failed")


class CodegenHandler(BaseHandler):
    """Handler for the Codegen service."""

    ollama_url: str = "http://localhost:11434"
    max_formulas_default: int = 50

    @route("POST", "/process")
    def handle_process(self, data: dict) -> dict | None:
        """Generate code for validated formulas.

        Request body:
            {
                "paper_id": 123,
                "formula_id": 456,
                "max_formulas": 50,
                "force": false
            }

        All fields optional. Without paper_id/formula_id, processes
        all stage='validated' formulas up to max_formulas.
        """
        start = time.time()

        paper_id = data.get("paper_id")
        formula_id = data.get("formula_id")
        max_formulas: int = data.get("max_formulas", self.max_formulas_default)
        force = data.get("force", False)

        assert self.db_path is not None, "db_path must be set"
        db_path: str = self.db_path

        formulas = _query_formulas(db_path, paper_id, formula_id,
                                   max_formulas, force)
        if not formulas:
            return {
                "success": True,
                "service": "codegen",
                "formulas_processed": 0,
                "code_generated": {"c99": 0, "rust": 0, "python": 0},
                "explanations_generated": 0,
                "errors": [],
                "time_ms": int((time.time() - start) * 1000),
            }

        errors: list[str] = []
        code_counts = {"c99": 0, "rust": 0, "python": 0}
        explanations_count = 0
        processed = 0

        # Batch explain: one LLM call per ~10 formulas instead of per-formula
        batch_results = explain_formulas_batch(formulas)

        for formula_row in formulas:
            fid = formula_row["id"]
            latex = formula_row["latex"]
            context = formula_row["context"]
            paper_title = formula_row["paper_title"]

            if not latex or not latex.strip():
                logger.warning("Formula %d has empty LaTeX, skipping", fid)
                continue

            try:
                # Step 1: LLM explanation — use batch result or fall back to per-formula
                explanation = batch_results.get(fid) or explain_formula(
                    latex, context, paper_title
                )
                if explanation:
                    _update_formula_description(
                        db_path, fid, json.dumps(explanation)
                    )
                    explanations_count += 1
                    logger.info("Formula %d: explanation generated", fid)
                else:
                    logger.warning(
                        "Formula %d: explanation failed, continuing with codegen",
                        fid,
                    )

                # Step 2: Code generation (C99, Rust, Python)
                code_results = generate_all(latex, fid)

                for cr in code_results:
                    _store_generated_code(
                        db_path, fid,
                        cr["language"], cr["code"],
                        cr["metadata"], cr["error"],
                    )
                    if cr["code"] and not cr["error"]:
                        code_counts[cr["language"]] += 1
                    elif cr["error"]:
                        errors.append(
                            f"formula {fid} {cr['language']}: {cr['error']}"
                        )

                # Step 3: Update stage if at least one language succeeded
                any_success = any(
                    cr["code"] and not cr["error"] for cr in code_results
                )
                if any_success:
                    _update_formula_stage(db_path, fid)
                else:
                    # All languages failed (likely parse_latex failure)
                    _mark_formula_failed(
                        db_path, fid,
                        "codegen: all languages failed",
                    )

                processed += 1

                logger.info(
                    "Formula %d: c99=%s rust=%s python=%s",
                    fid,
                    "ok" if code_results[0]["code"] else "fail",
                    "ok" if code_results[1]["code"] else "fail",
                    "ok" if code_results[2]["code"] else "fail",
                )

            except Exception as e:
                logger.error("Unexpected error for formula %d: %s", fid, e)
                errors.append(f"formula {fid}: {e}")
                _mark_formula_failed(db_path, fid, f"codegen: {e}")
                processed += 1

        elapsed_ms = int((time.time() - start) * 1000)

        # Update papers.stage if any code was successfully generated
        any_code = sum(code_counts.values()) > 0
        if any_code:
            paper_ids = {f["paper_id"] for f in formulas if f.get("paper_id")}
            for pid in paper_ids:
                _update_paper_stage(db_path, pid, "codegen")

        logger.info(
            "Codegen complete: processed=%d c99=%d rust=%d python=%d "
            "explanations=%d errors=%d time=%dms",
            processed, code_counts["c99"], code_counts["rust"],
            code_counts["python"], explanations_count,
            len(errors), elapsed_ms,
        )

        return {
            "success": True,
            "service": "codegen",
            "formulas_processed": processed,
            "code_generated": code_counts,
            "explanations_generated": explanations_count,
            "errors": errors,
            "time_ms": elapsed_ms,
        }


def _query_formulas(
    db_path: str,
    paper_id: int | None,
    formula_id: int | None,
    max_formulas: int,
    force: bool,
) -> list[dict]:
    """Query formulas ready for codegen.

    JOINs papers table to get paper title for LLM explanations.
    """
    base = (
        "SELECT f.*, p.title AS paper_title "
        "FROM formulas f "
        "LEFT JOIN papers p ON p.id = f.paper_id"
    )

    with transaction(db_path) as conn:
        if formula_id:
            cursor = conn.execute(
                f"{base} WHERE f.id = ?", (formula_id,)
            )
        elif paper_id:
            if force:
                cursor = conn.execute(
                    f"{base} WHERE f.paper_id = ? "
                    "AND f.stage IN ('validated', 'codegen') LIMIT ?",
                    (paper_id, max_formulas),
                )
            else:
                cursor = conn.execute(
                    f"{base} WHERE f.paper_id = ? "
                    "AND f.stage = 'validated' LIMIT ?",
                    (paper_id, max_formulas),
                )
        else:
            if force:
                cursor = conn.execute(
                    f"{base} WHERE f.stage IN ('validated', 'codegen') "
                    "LIMIT ?",
                    (max_formulas,),
                )
            else:
                cursor = conn.execute(
                    f"{base} WHERE f.stage = 'validated' LIMIT ?",
                    (max_formulas,),
                )
        return [dict(row) for row in cursor.fetchall()]


def _store_generated_code(
    db_path: str,
    formula_id: int,
    language: str,
    code: str,
    metadata: dict | None,
    error: str | None,
) -> None:
    """Store generated code. Overwrites existing for same formula+language."""
    with transaction(db_path) as conn:
        conn.execute(
            "DELETE FROM generated_code "
            "WHERE formula_id = ? AND language = ?",
            (formula_id, language),
        )
        conn.execute(
            "INSERT INTO generated_code "
            "(formula_id, language, code, metadata, error) "
            "VALUES (?, ?, ?, ?, ?)",
            (formula_id, language, code,
             json.dumps(metadata) if metadata else None,
             error),
        )


def _update_formula_description(
    db_path: str, formula_id: int, description_json: str
) -> None:
    """Store LLM explanation in formulas.description."""
    with transaction(db_path) as conn:
        conn.execute(
            "UPDATE formulas SET description = ? WHERE id = ?",
            (description_json, formula_id),
        )


def _update_formula_stage(db_path: str, formula_id: int) -> None:
    """Mark formula as codegen complete."""
    with transaction(db_path) as conn:
        conn.execute(
            "UPDATE formulas SET stage = 'codegen' WHERE id = ?",
            (formula_id,),
        )


def _update_paper_stage(db_path: str, paper_id: int, stage: str) -> None:
    """Update paper stage after processing its formulas."""
    with transaction(db_path) as conn:
        conn.execute(
            "UPDATE papers SET stage = ?, updated_at = datetime('now') WHERE id = ?",
            (stage, paper_id),
        )


def _mark_formula_failed(db_path: str, formula_id: int, error: str) -> None:
    """Mark a formula as failed."""
    with transaction(db_path) as conn:
        conn.execute(
            "UPDATE formulas SET stage = 'failed', error = ? WHERE id = ?",
            (error, formula_id),
        )


def main() -> None:
    """Start the Codegen service."""
    config = load_config("codegen")
    init_db(config.db_path)
    _check_consistency(str(config.db_path))

    CodegenHandler.ollama_url = os.environ.get(
        "RP_CODEGEN_OLLAMA_URL", "http://localhost:11434"
    )
    CodegenHandler.max_formulas_default = int(
        os.environ.get("RP_CODEGEN_MAX_FORMULAS", "50")
    )

    service = BaseService(
        "codegen", config.port, CodegenHandler, str(config.db_path)
    )
    service.run()


if __name__ == "__main__":
    main()
