"""RAGAnything HTTP client for PDF text extraction.

Submits PDFs to RAGAnything service, polls for completion,
and reads the resulting markdown output.

Uses urllib.request (stdlib) — no extra dependencies.
"""

from __future__ import annotations

import http.client
import json
import logging
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:8767"
DEFAULT_POLL_INTERVAL = 10
DEFAULT_TIMEOUT = 7200  # 2h — MinerU on CPU: ~10 min/page, 25-page paper = ~4h
DEFAULT_REQUEST_TIMEOUT = 30.0
DEFAULT_SUBMIT_TIMEOUT = 60.0
DEFAULT_REQUEST_RETRIES = 3
DEFAULT_RETRY_BACKOFF = 2.0

# Container→host path mapping for RAGAnything (host-based service)
_PDF_DIR = os.environ.get("RP_EXTRACTOR_PDF_DIR", "/data/pdfs")
_PDF_HOST_DIR = os.environ.get("RP_EXTRACTOR_PDF_HOST_DIR", "")
_PROJECT_HOST_DIR = os.environ.get("RP_EXTRACTOR_PROJECT_HOST_DIR", "")
_RAG_DATA_HOST = os.environ.get("RP_EXTRACTOR_RAG_DATA_HOST", "")


def _resolve_host_dir(path_str: str) -> str:
    if not path_str:
        return ""
    path = Path(path_str)
    if path.is_absolute() or not _PROJECT_HOST_DIR:
        return str(path)
    return str((Path(_PROJECT_HOST_DIR) / path).resolve())


def _resolved_pdf_host_dir() -> str:
    return _resolve_host_dir(_PDF_HOST_DIR)


def _resolved_rag_data_host() -> str:
    return _resolve_host_dir(_RAG_DATA_HOST)


def _request_retries() -> int:
    return max(1, int(os.environ.get("RP_EXTRACTOR_RAG_RETRIES", str(DEFAULT_REQUEST_RETRIES))))


def _retry_backoff() -> float:
    return max(0.0, float(os.environ.get("RP_EXTRACTOR_RAG_RETRY_BACKOFF", str(DEFAULT_RETRY_BACKOFF))))


def _request_timeout() -> float:
    return max(
        1.0,
        float(
            os.environ.get(
                "RP_EXTRACTOR_RAG_REQUEST_TIMEOUT",
                str(DEFAULT_REQUEST_TIMEOUT),
            )
        ),
    )


def _submit_timeout() -> float:
    return max(
        _request_timeout(),
        float(
            os.environ.get(
                "RP_EXTRACTOR_RAG_SUBMIT_TIMEOUT",
                str(DEFAULT_SUBMIT_TIMEOUT),
            )
        ),
    )


def _is_retryable_http_error(exc: BaseException) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in {408, 429, 500, 502, 503, 504}
    return isinstance(
        exc,
        (
            urllib.error.URLError,
            TimeoutError,
            ConnectionError,
            ConnectionResetError,
            http.client.HTTPException,
            OSError,
        ),
    )


def _json_request(
    url_or_req: str | urllib.request.Request,
    *,
    timeout: float,
    attempts: int | None = None,
    backoff: float | None = None,
    deadline: float | None = None,
    label: str,
) -> dict:
    """Open a JSON endpoint with retry/backoff for transient transport failures."""
    if attempts is None:
        attempts = _request_retries()
    if backoff is None:
        backoff = _retry_backoff()

    last_error: BaseException | None = None
    for attempt in range(1, attempts + 1):
        request_timeout = timeout
        if deadline is not None:
            remaining = deadline - time.time()
            if remaining <= 0:
                if last_error is not None:
                    raise last_error
                raise TimeoutError(f"RAG request {label} timed out")
            request_timeout = min(request_timeout, remaining)
        try:
            resp = urllib.request.urlopen(url_or_req, timeout=request_timeout)
            return json.loads(resp.read().decode())
        except Exception as exc:
            last_error = exc
            retryable = _is_retryable_http_error(exc)
            if not retryable or attempt >= attempts:
                raise
            sleep_for = backoff * attempt
            if deadline is not None:
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise
                sleep_for = min(sleep_for, remaining)
            logger.warning(
                "RAG request failed (%s), retrying %d/%d in %.1fs: %s",
                label, attempt, attempts, sleep_for, exc,
            )
            time.sleep(sleep_for)

    raise RuntimeError(f"Unreachable retry state for {label}: {last_error}")


def check_service(base_url: str = DEFAULT_BASE_URL) -> dict:
    """Check RAGAnything availability and circuit breaker state.

    Raises:
        RuntimeError: If circuit breaker is open or service unreachable.
    """
    data = _json_request(
        f"{base_url}/status",
        timeout=_request_timeout(),
        label="status",
    )

    if data.get("circuit_breaker", {}).get("state") == "open":
        raise RuntimeError("RAGAnything circuit breaker is open")

    return data


def _map_to_host_path(container_path: Path) -> str:
    """Map container PDF path to host path for RAGAnything."""
    path_str = str(container_path)
    pdf_host_dir = _resolved_pdf_host_dir()
    if pdf_host_dir and path_str.startswith(_PDF_DIR):
        mapped = path_str.replace(_PDF_DIR, pdf_host_dir, 1)
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
    # /process creates server-side work, so transport errors must not replay it.
    data = _json_request(
        req,
        timeout=_submit_timeout(),
        attempts=1,
        label=f"submit:{paper_id}",
    )

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

    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        try:
            data = _json_request(
                f"{base_url}/jobs/{job_id}",
                timeout=min(_request_timeout(), remaining),
                deadline=deadline,
                label=f"job:{job_id}",
            )
        except Exception as exc:
            if not _is_retryable_http_error(exc):
                raise
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            sleep_for = min(interval, remaining)
            logger.warning(
                "Transient RAG polling error for %s, retrying in %.1fs: %s",
                job_id, sleep_for, exc,
            )
            time.sleep(sleep_for)
            continue

        if data["status"] == "completed":
            return data["result"]
        if data["status"] == "failed":
            raise RuntimeError(
                f"RAGAnything job {job_id} failed: {data.get('error')}"
            )

        remaining = deadline - time.time()
        if remaining <= 0:
            break
        sleep_for = min(interval, remaining)
        logger.debug(
            "Job %s status: %s, waiting %.1fs",
            job_id,
            data["status"],
            sleep_for,
        )
        time.sleep(sleep_for)

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
    rag_data_host = _resolved_rag_data_host()
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
