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

from shared.config import load_config
from shared.db import init_db
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
