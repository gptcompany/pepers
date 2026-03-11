"""PDF download from arXiv with retry and caching.

Downloads papers from export.arxiv.org (bulk access endpoint).
Uses requests with exponential backoff for rate limiting.
Caches PDFs locally to avoid re-downloading.
"""

from __future__ import annotations

import logging
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from shared.models import Paper

logger = logging.getLogger(__name__)

EXPORT_BASE = "https://export.arxiv.org/pdf"
USER_AGENT = "ResearchPipeline/1.0 (academic-formula-extraction)"
DOWNLOAD_TIMEOUT = 60


def has_download_source(paper: Paper) -> bool:
    """Return True when a paper has enough metadata to attempt PDF download."""
    return bool((paper.pdf_url or "").strip() or (paper.arxiv_id or "").strip())


def create_session() -> requests.Session:
    """Create a reusable session with retry strategy."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "application/pdf",
    })
    retry = Retry(
        total=3,
        backoff_factor=2.0,
        status_forcelist=[429, 500, 502, 503, 504],
        respect_retry_after_header=True,
        allowed_methods=["GET"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def get_pdf_url(paper: Paper) -> str:
    """Return PDF URL, preferring stored pdf_url, falling back to constructed."""
    if paper.pdf_url:
        url = paper.pdf_url.replace("http://arxiv.org", "https://export.arxiv.org")
        url = url.replace("https://arxiv.org", "https://export.arxiv.org")
        return url
    if not paper.arxiv_id:
        raise ValueError("no downloadable PDF source (missing arxiv_id and pdf_url)")
    return f"{EXPORT_BASE}/{paper.arxiv_id}"


def download_pdf(
    paper: Paper, dest_dir: Path, session: requests.Session | None = None
) -> Path:
    """Download PDF to local filesystem. Skip if already cached.

    Args:
        paper: Paper with arxiv_id and optional pdf_url.
        dest_dir: Directory to store PDFs.
        session: Optional reusable requests session.

    Returns:
        Path to the downloaded PDF file.

    Raises:
        requests.HTTPError: On download failure after retries.
        RuntimeError: If response is not a PDF.
    """
    if session is None:
        session = create_session()

    url = get_pdf_url(paper)
    safe_name = (paper.arxiv_id or f"paper-{paper.id or 'unknown'}").replace("/", "_")
    dest_path = dest_dir / f"{safe_name}.pdf"

    # Cache check
    if dest_path.exists() and dest_path.stat().st_size > 1000:
        logger.debug("PDF cached: %s", dest_path)
        return dest_path

    logger.info("Downloading PDF: %s → %s", url, dest_path)
    resp = session.get(url, timeout=DOWNLOAD_TIMEOUT, stream=True)
    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "")
    if "pdf" not in content_type:
        raise RuntimeError(f"Expected PDF, got {content_type} for {paper.arxiv_id}")

    dest_dir.mkdir(parents=True, exist_ok=True)
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)

    logger.info("Downloaded %s (%d bytes)", paper.arxiv_id, dest_path.stat().st_size)
    return dest_path
