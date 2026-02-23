"""RAGAnything HTTP client for PDF text extraction.

Submits PDFs to RAGAnything service, polls for completion,
and reads the resulting markdown output.

Uses urllib.request (stdlib) — no extra dependencies.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:8767"
DEFAULT_POLL_INTERVAL = 10
DEFAULT_TIMEOUT = 7200  # 2h — MinerU on CPU: ~10 min/page, 25-page paper = ~4h

# Container→host path mapping for RAGAnything (host-based service)
_PDF_DIR = os.environ.get("RP_EXTRACTOR_PDF_DIR", "/data/pdfs")
_PDF_HOST_DIR = os.environ.get("RP_EXTRACTOR_PDF_HOST_DIR", "")


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


def _map_to_host_path(container_path: Path) -> str:
    """Map container PDF path to host path for RAGAnything."""
    path_str = str(container_path)
    if _PDF_HOST_DIR and path_str.startswith(_PDF_DIR):
        mapped = path_str.replace(_PDF_DIR, _PDF_HOST_DIR, 1)
        logger.debug("Path mapped: %s → %s", path_str, mapped)
        return mapped
    return path_str


def submit_pdf(
    pdf_path: Path, paper_id: str, base_url: str = DEFAULT_BASE_URL
) -> dict:
    """Submit PDF to RAGAnything for processing.

    Returns:
        Dict with 'cached' bool and either 'result' or 'job_id'.
    """
    host_path = _map_to_host_path(pdf_path)
    payload = json.dumps({
        "pdf_path": host_path,
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
    Tries multiple path mappings to support both Docker and host execution.

    Raises:
        FileNotFoundError: If no markdown files found.
    """
    # Path mappings to try (RAGAnything output → accessible path)
    # Configure via RP_EXTRACTOR_PATH_MAPPINGS="src1:dst1,src2:dst2"
    candidates = [output_dir]
    custom = os.environ.get("RP_EXTRACTOR_PATH_MAPPINGS", "")
    if custom:
        for mapping in custom.split(","):
            if ":" in mapping:
                src, dst = mapping.split(":", 1)
                candidates.append(output_dir.replace(src, dst))
    # Docker container: RAG data mounted at /rag-data
    rag_data_host = os.environ.get("RP_EXTRACTOR_RAG_DATA_HOST", "")
    if rag_data_host:
        candidates.append(output_dir.replace(rag_data_host, "/rag-data"))

    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            md_files = list(path.glob("**/*.md"))
            if md_files:
                md_files.sort(key=lambda f: f.stat().st_size, reverse=True)
                logger.debug("Reading markdown from: %s", md_files[0])
                return md_files[0].read_text(encoding="utf-8")

    raise FileNotFoundError(
        f"No markdown files found. Tried: {[c for c in candidates if c != output_dir]}"
    )


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
