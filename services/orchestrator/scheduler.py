"""Cron scheduler for automatic pipeline execution.

Uses APScheduler BackgroundScheduler to trigger pipeline runs on a
configurable cron schedule. Runs in a background thread alongside
the HTTP server.

Environment:
    RP_ORCHESTRATOR_CRON=0 8 * * *          # Cron expression (default: daily 08:00)
    RP_ORCHESTRATOR_CRON_ENABLED=true       # Enable/disable scheduler
"""

from __future__ import annotations

import logging
import os
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


def create_scheduler(run_func: Callable[[], None]) -> BackgroundScheduler | None:
    """Create and configure the cron scheduler.

    Args:
        run_func: Function to call on each cron trigger.

    Returns:
        Configured scheduler, or None if disabled.
    """
    enabled = os.environ.get(
        "RP_ORCHESTRATOR_CRON_ENABLED", "false"
    ).lower() in ("true", "1", "yes")

    if not enabled:
        logger.info("Cron scheduler disabled (RP_ORCHESTRATOR_CRON_ENABLED)")
        return None

    cron_expr = os.environ.get("RP_ORCHESTRATOR_CRON", "0 8 * * *")

    scheduler = BackgroundScheduler(daemon=True)
    trigger = CronTrigger.from_crontab(cron_expr)
    scheduler.add_job(run_func, trigger, id="pipeline_cron", name="pipeline_cron")

    logger.info("Cron scheduler configured: %s", cron_expr)
    return scheduler
