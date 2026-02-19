"""Multi-target notifications via Apprise.

Sends pipeline completion/failure notifications to any service
supported by Apprise (Discord, Slack, Telegram, Matrix, email, etc.).

Configuration:
    RP_NOTIFY_URLS  Comma-separated Apprise URLs.
                    Example: discord://id/token,tgram://bot/chat
                    Empty or unset = notifications disabled (silent).
"""

from __future__ import annotations

import logging
import os

import apprise

logger = logging.getLogger(__name__)


def notify(title: str, body: str) -> int:
    """Send notification to all configured targets.

    Returns the number of targets notified (0 if none configured).
    """
    urls = os.environ.get("RP_NOTIFY_URLS", "")
    if not urls.strip():
        return 0

    ap = apprise.Apprise()
    for url in urls.split(","):
        url = url.strip()
        if url:
            ap.add(url)

    if len(ap) == 0:
        return 0

    count = len(ap)
    try:
        ap.notify(title=title, body=body)
    except Exception:
        logger.exception("Failed to send notification to %d target(s)", count)
        return 0

    logger.info("Notification sent to %d target(s)", count)
    return count


def notify_pipeline_result(result: dict) -> int:
    """Format and send notification for a pipeline run result."""
    status = result.get("status", "unknown")
    stages = (
        f"{result.get('stages_completed', '?')}"
        f"/{result.get('stages_requested', '?')}"
    )
    time_s = round(result.get("time_ms", 0) / 1000, 1)

    tag = {"completed": "OK", "partial": "WARN", "failed": "FAIL"}.get(
        status, "?"
    )
    title = f"[{tag}] Research Pipeline - {status}"

    lines = [
        f"Run: {result.get('run_id', 'N/A')}",
        f"Stages: {stages}",
        f"Time: {time_s}s",
    ]
    errors = result.get("errors", [])
    if errors:
        lines.append(f"Errors: {', '.join(str(e) for e in errors[:3])}")

    return notify(title, "\n".join(lines))
