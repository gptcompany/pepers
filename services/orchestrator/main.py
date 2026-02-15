"""Orchestrator service — pipeline coordination and cron scheduling.

Sixth microservice in the research pipeline. Coordinates the 5
downstream services (Discovery → Analyzer → Extractor → Validator →
Codegen) via HTTP calls to their /process endpoints.

Usage:
    python -m services.orchestrator.main

Environment:
    RP_ORCHESTRATOR_PORT=8775               # Service port (default: 8775)
    RP_ORCHESTRATOR_CRON=0 8 * * *          # Cron expression
    RP_ORCHESTRATOR_CRON_ENABLED=false      # Enable cron (default: disabled)
    RP_ORCHESTRATOR_STAGES_PER_RUN=5        # Stages per cron run
    RP_ORCHESTRATOR_DEFAULT_QUERY=...       # Default arXiv query for cron
    RP_ORCHESTRATOR_CRON_MAX_PAPERS=10      # Max papers per cron batch
    RP_ORCHESTRATOR_CRON_MAX_FORMULAS=50    # Max formulas per cron batch
    RP_ORCHESTRATOR_RETRY_MAX=3             # Max retries per service call
    RP_ORCHESTRATOR_RETRY_BACKOFF=4.0       # Backoff base (seconds)
    RP_ORCHESTRATOR_TIMEOUT=300             # Request timeout (seconds)
    RP_DB_PATH=data/research.db             # SQLite database path
    RP_LOG_LEVEL=INFO                       # Log level
"""

from __future__ import annotations

import logging
import os
import time
from urllib.parse import parse_qs

from shared.config import load_config
from shared.db import init_db, transaction
from shared.models import Formula, Paper
from shared.server import BaseHandler, BaseService, route

from services.orchestrator.pipeline import PipelineRunner
from services.orchestrator.scheduler import create_scheduler

logger = logging.getLogger(__name__)


class OrchestratorHandler(BaseHandler):
    """Handler for the Orchestrator service."""

    runner: PipelineRunner | None = None

    @route("POST", "/run")
    def handle_run(self, data: dict) -> dict | None:
        """Trigger a pipeline run.

        Request body:
            {
                "query": "abs:\"Kelly criterion\" AND cat:q-fin.*",
                "paper_id": 42,
                "stages": 5,
                "max_papers": 10,
                "max_formulas": 50,
                "force": false
            }

        All fields optional.
        """
        assert self.runner is not None, "PipelineRunner not initialized"

        query = data.get("query")
        paper_id = data.get("paper_id")
        stages = data.get("stages", 5)
        max_papers = data.get("max_papers", 10)
        max_formulas = data.get("max_formulas", 50)
        force = data.get("force", False)

        # Validate
        if paper_id is not None and not isinstance(paper_id, int):
            self.send_error_json(
                "paper_id must be an integer", "VALIDATION_ERROR", 400
            )
            return None
        if not 1 <= stages <= 5:
            self.send_error_json(
                "stages must be between 1 and 5", "VALIDATION_ERROR", 400
            )
            return None

        logger.info(
            "Pipeline run: query=%s paper_id=%s stages=%d",
            query, paper_id, stages,
        )

        result = self.runner.run(
            query=query,
            paper_id=paper_id,
            stages=stages,
            max_papers=max_papers,
            max_formulas=max_formulas,
            force=force,
        )

        return result

    @route("GET", "/status")
    def handle_status(self) -> dict:
        """Get aggregate pipeline status."""
        assert self.runner is not None, "PipelineRunner not initialized"

        status = self.runner.get_pipeline_status()

        # Add cron info
        cron_enabled = os.environ.get(
            "RP_ORCHESTRATOR_CRON_ENABLED", "false"
        ).lower() in ("true", "1", "yes")
        cron_expr = os.environ.get("RP_ORCHESTRATOR_CRON", "0 8 * * *")

        status["cron"] = {
            "enabled": cron_enabled,
            "schedule": cron_expr,
        }

        return status

    @route("GET", "/status/services")
    def handle_services_status(self) -> dict:
        """Check health of all downstream services."""
        assert self.runner is not None, "PipelineRunner not initialized"
        return self.runner.get_services_health()

    # -- Query endpoints for reading pipeline data --

    def _query_params(self) -> dict[str, str]:
        """Parse query string from self.path into {key: value} dict."""
        qs = self.path.split("?", 1)[1] if "?" in self.path else ""
        raw = parse_qs(qs, keep_blank_values=False)
        return {k: v[0] for k, v in raw.items()}

    @route("GET", "/papers")
    def handle_papers(self) -> dict | list | None:
        """Query papers from the pipeline database.

        GET /papers?stage=analyzed&limit=50  → list papers
        GET /papers?id=42                    → single paper with formulas,
                                               validations, and generated code
        """
        params = self._query_params()
        paper_id = params.get("id")

        if paper_id is not None:
            return self._get_paper_detail(int(paper_id))

        stage = params.get("stage")
        limit = min(int(params.get("limit", "50")), 200)
        return self._list_papers(stage=stage, limit=limit)

    @route("GET", "/formulas")
    def handle_formulas(self) -> list | None:
        """Query formulas from the pipeline database.

        GET /formulas?paper_id=42&stage=validated&limit=50
        """
        params = self._query_params()
        paper_id = params.get("paper_id")
        stage = params.get("stage")
        limit = min(int(params.get("limit", "50")), 200)

        clauses = []
        bind: list = []
        if paper_id is not None:
            clauses.append("f.paper_id = ?")
            bind.append(int(paper_id))
        if stage:
            clauses.append("f.stage = ?")
            bind.append(stage)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        with transaction(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT f.* FROM formulas f {where} "  # noqa: S608
                f"ORDER BY f.id DESC LIMIT ?",
                [*bind, limit],
            ).fetchall()
        return [Formula(**dict(r)).model_dump(mode="json") for r in rows]

    # -- Helpers for paper queries --

    def _list_papers(
        self, *, stage: str | None = None, limit: int = 50
    ) -> list[dict]:
        clauses = []
        bind: list = []
        if stage:
            clauses.append("p.stage = ?")
            bind.append(stage)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        with transaction(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT p.* FROM papers p {where} "  # noqa: S608
                f"ORDER BY p.created_at DESC LIMIT ?",
                [*bind, limit],
            ).fetchall()
        return [Paper(**dict(r)).model_dump(mode="json") for r in rows]

    def _get_paper_detail(self, paper_id: int) -> dict | None:
        with transaction(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM papers WHERE id = ?", [paper_id]
            ).fetchone()
            if row is None:
                self.send_error_json(
                    f"Paper {paper_id} not found", "NOT_FOUND", 404
                )
                return None

            paper = Paper(**dict(row)).model_dump(mode="json")

            # Formulas for this paper
            f_rows = conn.execute(
                "SELECT * FROM formulas WHERE paper_id = ? ORDER BY id",
                [paper_id],
            ).fetchall()
            formulas = []
            for fr in f_rows:
                formula = Formula(**dict(fr)).model_dump(mode="json")

                # Validations for this formula
                v_rows = conn.execute(
                    "SELECT * FROM validations WHERE formula_id = ? "
                    "ORDER BY id",
                    [fr["id"]],
                ).fetchall()
                formula["validations"] = [dict(vr) for vr in v_rows]

                # Generated code for this formula
                gc_rows = conn.execute(
                    "SELECT * FROM generated_code WHERE formula_id = ? "
                    "ORDER BY id",
                    [fr["id"]],
                ).fetchall()
                formula["generated_code"] = [dict(gcr) for gcr in gc_rows]

                formulas.append(formula)

            paper["formulas"] = formulas
        return paper


def _cron_run() -> None:
    """Executed by APScheduler on each cron trigger."""
    runner = OrchestratorHandler.runner
    if runner is None:
        logger.error("Cron trigger but PipelineRunner not initialized")
        return

    query = os.environ.get(
        "RP_ORCHESTRATOR_DEFAULT_QUERY",
        'abs:"Kelly criterion" AND cat:q-fin.*',
    )
    stages = int(os.environ.get("RP_ORCHESTRATOR_STAGES_PER_RUN", "5"))
    max_papers = int(os.environ.get("RP_ORCHESTRATOR_CRON_MAX_PAPERS", "10"))
    max_formulas = int(os.environ.get("RP_ORCHESTRATOR_CRON_MAX_FORMULAS", "50"))

    logger.info("Cron run starting: query=%s stages=%d", query, stages)
    start = time.time()

    try:
        result = runner.run(
            query=query,
            stages=stages,
            max_papers=max_papers,
            max_formulas=max_formulas,
        )
        elapsed = int((time.time() - start) * 1000)
        logger.info(
            "Cron run complete: status=%s stages=%d/%d time=%dms",
            result["status"],
            result["stages_completed"],
            result["stages_requested"],
            elapsed,
        )
    except Exception:
        logger.exception("Cron run failed")


def main() -> None:
    """Start the Orchestrator service."""
    config = load_config("orchestrator")
    init_db(config.db_path)

    # Initialize pipeline runner
    runner = PipelineRunner(config.db_path)
    OrchestratorHandler.runner = runner

    # Create scheduler (if enabled)
    scheduler = create_scheduler(_cron_run)

    if scheduler:
        scheduler.start()
        logger.info("Cron scheduler started")

    # Start HTTP server (blocking)
    service = BaseService(
        "orchestrator", config.port, OrchestratorHandler, str(config.db_path)
    )

    try:
        service.run()
    finally:
        if scheduler:
            scheduler.shutdown(wait=False)
            logger.info("Cron scheduler stopped")


if __name__ == "__main__":
    main()
