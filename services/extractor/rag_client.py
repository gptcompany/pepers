"""RAGAnything HTTP client for PDF text extraction.

Submits PDFs to RAGAnything service, polls for completion,
and reads the resulting markdown output.

Uses urllib.request (stdlib) — no extra dependencies.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:8767"
DEFAULT_POLL_INTERVAL = 10
DEFAULT_TIMEOUT = 600


def check_service(base_url: str = DEFAULT_BASE_URL) -> dict:
    """Check RAGAnything availability and circuit breaker state.

    Raises:
        RuntimeError: If circuit breaker is open or service unreachable.
    """
    resp = urllib.request.urlopen(f"{base_url}/status", timeout=10)
    data = json.loads(resp.read().decode())

    if data.get("circuit_breaker", {}).get("state") == "open":
        raise RuntimeError("RAGAnything circuit breaker is open")

    return data


def submit_pdf(
    pdf_path: Path, paper_id: str, base_url: str = DEFAULT_BASE_URL
) -> dict:
    """Submit PDF to RAGAnything for processing.

    Returns:
        Dict with 'cached' bool and either 'result' or 'job_id'.
    """
    payload = json.dumps({
        "pdf_path": str(pdf_path),
        "paper_id": paper_id,
    }).encode()

    req = urllib.request.Request(
        f"{base_url}/process",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=30)
    data = json.loads(resp.read().decode())

    if data.get("cached"):
        return {"cached": True, "result": data}

    return {"cached": False, "job_id": data["job_id"]}


def poll_job(
    job_id: str,
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = DEFAULT_TIMEOUT,
    interval: float = DEFAULT_POLL_INTERVAL,
) -> dict:
    """Poll job status until completion or timeout.

    Raises:
        RuntimeError: If job failed.
        TimeoutError: If job didn't complete within timeout.
    """
    deadline = time.time() + timeout

    while time.time() < deadline:
        resp = urllib.request.urlopen(
            f"{base_url}/jobs/{job_id}", timeout=10
        )
        data = json.loads(resp.read().decode())

        if data["status"] == "completed":
            return data["result"]
        if data["status"] == "failed":
            raise RuntimeError(
                f"RAGAnything job {job_id} failed: {data.get('error')}"
            )

        logger.debug("Job %s status: %s, waiting %ds", job_id, data["status"], interval)
        time.sleep(interval)

    raise TimeoutError(f"RAGAnything job {job_id} timed out after {timeout}s")


def read_markdown(output_dir: str) -> str:
    """Read markdown output from RAGAnything's extraction directory.

    Handles container→host path mapping and finds the largest .md file.

    Raises:
        FileNotFoundError: If no markdown files found.
    """
    # Handle container path mapping
    host_dir = output_dir.replace("/workspace/1TB/", "/media/sam/1TB/")
    host_dir = host_dir.replace("/workspace/3TB-WDC/", "/media/sam/3TB-WDC/")

    path = Path(host_dir)
    md_files = list(path.glob("**/*.md"))
    if not md_files:
        raise FileNotFoundError(f"No markdown files in {host_dir}")

    # Read largest .md file (the main extraction output)
    md_files.sort(key=lambda f: f.stat().st_size, reverse=True)
    return md_files[0].read_text(encoding="utf-8")


def process_paper(
    pdf_path: Path, paper_id: str, base_url: str = DEFAULT_BASE_URL
) -> str:
    """High-level orchestration: check service, submit, poll, read markdown.

    Args:
        pdf_path: Local path to the PDF file.
        paper_id: arXiv ID for the paper.
        base_url: RAGAnything base URL.

    Returns:
        Extracted markdown text.

    Raises:
        RuntimeError: On service or processing errors.
    """
    check_service(base_url)

    result = submit_pdf(pdf_path, paper_id, base_url)

    if result["cached"]:
        output_dir = result["result"].get("output_dir", "")
    else:
        job_result = poll_job(result["job_id"], base_url)
        output_dir = job_result.get("output_dir", "")

    if not output_dir:
        raise RuntimeError(f"No output_dir in RAGAnything result for {paper_id}")

    return read_markdown(output_dir)
