"""Validator service — multi-CAS formula validation with consensus.

Fourth microservice in the research pipeline. Reads formulas with
stage='extracted', sends to CAS microservice for validation, applies
consensus logic, and stores results in the validations table.

Usage:
    python -m services.validator.main

Environment:
    RP_VALIDATOR_PORT=8773                    # Service port (default: 8773)
    RP_VALIDATOR_CAS_URL=http://localhost:8769 # CAS microservice URL
    RP_VALIDATOR_MAX_FORMULAS=50              # Default batch size
    RP_VALIDATOR_ENGINES=matlab,sympy,maxima   # Comma-separated engine list
    RP_DB_PATH=data/research.db              # SQLite database path
    RP_LOG_LEVEL=INFO                        # Log level
"""

from __future__ import annotations

import logging
import os
import time

from shared.config import load_config
from shared.db import init_db, transaction
from shared.server import BaseHandler, BaseService, route

from services.validator.cas_client import CASClient, CASServiceError
from services.validator.consensus import (
    ConsensusOutcome,
    ConsensusResult,
    apply_consensus,
)

logger = logging.getLogger(__name__)


class ValidatorHandler(BaseHandler):
    """Handler for the Validator service."""

    cas_url: str = "http://localhost:8769"
    cas_timeout: int = 120
    max_formulas_default: int = 50
    engines: list[str] = ["matlab", "sympy", "maxima"]

    @route("POST", "/process")
    def handle_process(self, data: dict) -> dict | None:
        """Validate extracted formulas via CAS service.

        Request body:
            {
                "paper_id": 123,
                "formula_id": 456,
                "max_formulas": 50,
                "force": false,
                "engines": ["matlab", "sympy", "maxima"]
            }
        """
        start = time.time()

        paper_id = data.get("paper_id")
        formula_id = data.get("formula_id")
        max_formulas: int = data.get("max_formulas", self.max_formulas_default)
        force = data.get("force", False)
        engines = data.get("engines", self.engines)

        assert self.db_path is not None, "db_path must be set"
        db_path: str = self.db_path

        formulas = _query_formulas(db_path, paper_id, formula_id,
                                   max_formulas, force)
        if not formulas:
            return {
                "success": True,
                "service": "validator",
                "formulas_processed": 0,
                "formulas_valid": 0,
                "formulas_invalid": 0,
                "formulas_partial": 0,
                "formulas_unparseable": 0,
                "formulas_failed": 0,
                "errors": [],
                "time_ms": int((time.time() - start) * 1000),
            }

        client = CASClient(base_url=self.cas_url, timeout=self.cas_timeout)

        # Check CAS service health before batch
        if not client.health():
            self.send_error_json(
                "CAS service is not available", "SERVICE_UNAVAILABLE", 503
            )
            return None

        errors: list[str] = []
        counts = {
            "valid": 0,
            "invalid": 0,
            "partial": 0,
            "unparseable": 0,
            "failed": 0,
        }
        details: list[dict] = []

        for formula_row in formulas:
            fid = formula_row["id"]
            latex = formula_row["latex"]

            if not latex or not latex.strip():
                logger.warning("Formula %d has empty LaTeX, skipping", fid)
                continue

            try:
                cas_response = client.validate(latex, engines)
                _store_validations(db_path, fid, cas_response.results)
                consensus = apply_consensus(cas_response.results)
                _update_formula_stage(db_path, fid, consensus)

                counts[consensus.outcome.value] += 1

                # Include details for small batches
                if len(formulas) <= 10:
                    engine_detail = {}
                    for r in cas_response.results:
                        engine_detail[r.engine] = {
                            "success": r.success,
                            "is_valid": r.is_valid,
                            "time_ms": r.time_ms,
                        }
                    details.append({
                        "formula_id": fid,
                        "latex_hash": formula_row.get("latex_hash", ""),
                        "consensus": consensus.outcome.value,
                        "engines": engine_detail,
                    })

                logger.info(
                    "Formula %d: consensus=%s (%s)",
                    fid, consensus.outcome.value, consensus.detail,
                )

            except CASServiceError as e:
                logger.error("CAS error for formula %d: %s", fid, e)
                errors.append(f"formula {fid}: {e}")
                _mark_formula_failed(db_path, fid, str(e))
                counts["failed"] += 1

            except Exception as e:
                logger.error("Unexpected error for formula %d: %s", fid, e)
                errors.append(f"formula {fid}: {e}")
                _mark_formula_failed(db_path, fid, str(e))
                counts["failed"] += 1

        elapsed_ms = int((time.time() - start) * 1000)
        processed = sum(counts.values())

        logger.info(
            "Validation complete: processed=%d valid=%d invalid=%d "
            "partial=%d unparseable=%d failed=%d errors=%d time=%dms",
            processed, counts["valid"], counts["invalid"],
            counts["partial"], counts["unparseable"],
            counts["failed"], len(errors), elapsed_ms,
        )

        result = {
            "success": True,
            "service": "validator",
            "formulas_processed": processed,
            "formulas_valid": counts["valid"],
            "formulas_invalid": counts["invalid"],
            "formulas_partial": counts["partial"],
            "formulas_unparseable": counts["unparseable"],
            "formulas_failed": counts["failed"],
            "errors": errors,
            "time_ms": elapsed_ms,
        }
        if details:
            result["details"] = details
        return result


def _query_formulas(
    db_path: str,
    paper_id: int | None,
    formula_id: int | None,
    max_formulas: int,
    force: bool,
) -> list[dict]:
    """Query formulas ready for validation."""
    with transaction(db_path) as conn:
        if formula_id:
            cursor = conn.execute(
                "SELECT * FROM formulas WHERE id = ?", (formula_id,)
            )
        elif paper_id:
            if force:
                cursor = conn.execute(
                    "SELECT * FROM formulas WHERE paper_id = ? "
                    "AND stage IN ('extracted', 'validated') LIMIT ?",
                    (paper_id, max_formulas),
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM formulas WHERE paper_id = ? "
                    "AND stage = 'extracted' LIMIT ?",
                    (paper_id, max_formulas),
                )
        else:
            if force:
                cursor = conn.execute(
                    "SELECT * FROM formulas "
                    "WHERE stage IN ('extracted', 'validated') LIMIT ?",
                    (max_formulas,),
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM formulas WHERE stage = 'extracted' LIMIT ?",
                    (max_formulas,),
                )
        return [dict(row) for row in cursor.fetchall()]


def _store_validations(
    db_path: str,
    formula_id: int,
    engine_results: list,
) -> None:
    """Store per-engine validation results. Overwrites existing for same formula+engine."""
    with transaction(db_path) as conn:
        for r in engine_results:
            conn.execute(
                "DELETE FROM validations WHERE formula_id = ? AND engine = ?",
                (formula_id, r.engine),
            )
            conn.execute(
                "INSERT INTO validations "
                "(formula_id, engine, is_valid, result, error, time_ms) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (formula_id, r.engine, r.is_valid, r.simplified,
                 r.error, r.time_ms),
            )


def _update_formula_stage(
    db_path: str,
    formula_id: int,
    consensus: ConsensusResult,
) -> None:
    """Update formula stage based on consensus outcome.

    VALID/INVALID/PARTIAL → 'validated'
    UNPARSEABLE → no change (leave as 'extracted')
    """
    if consensus.outcome == ConsensusOutcome.UNPARSEABLE:
        return

    with transaction(db_path) as conn:
        conn.execute(
            "UPDATE formulas SET stage = 'validated' WHERE id = ?",
            (formula_id,),
        )


def _mark_formula_failed(db_path: str, formula_id: int, error: str) -> None:
    """Mark a formula as failed (CAS service error)."""
    with transaction(db_path) as conn:
        conn.execute(
            "UPDATE formulas SET stage = 'failed', error = ? WHERE id = ?",
            (f"validator: {error}", formula_id),
        )


def main() -> None:
    """Start the Validator service."""
    config = load_config("validator")
    init_db(config.db_path)

    ValidatorHandler.cas_url = os.environ.get(
        "RP_VALIDATOR_CAS_URL", "http://localhost:8769"
    )
    ValidatorHandler.cas_timeout = int(
        os.environ.get("RP_VALIDATOR_CAS_TIMEOUT", "120")
    )
    ValidatorHandler.max_formulas_default = int(
        os.environ.get("RP_VALIDATOR_MAX_FORMULAS", "50")
    )
    engines_str = os.environ.get("RP_VALIDATOR_ENGINES", "matlab,sympy,maxima")
    ValidatorHandler.engines = [e.strip() for e in engines_str.split(",")]

    service = BaseService(
        "validator", config.port, ValidatorHandler, str(config.db_path)
    )
    service.run()


if __name__ == "__main__":
    main()
