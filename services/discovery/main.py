"""Discovery service — searches arXiv/OpenAlex, enriches with Semantic Scholar and CrossRef.

First microservice in the research pipeline. Accepts search queries via POST /process,
discovers papers on arXiv and/or OpenAlex, enriches each with citation data from
Semantic Scholar and optionally CrossRef (when a journal DOI exists).
All data persists to SQLite via shared lib.

Usage:
    python -m services.discovery.main

Environment:
    RP_DISCOVERY_PORT=8770            # Service port (default: 8770)
    RP_DB_PATH=data/research.db       # SQLite database path
    RP_DISCOVERY_MAX_RESULTS=50       # Default max results per query
    RP_DISCOVERY_SOURCES=arxiv        # Comma-separated: arxiv,openalex
    RP_LOG_LEVEL=INFO                 # Log level
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

import arxiv
import requests

from shared.config import load_config
from shared.db import init_db, transaction
from shared.server import BaseHandler, BaseService, route

logger = logging.getLogger(__name__)

# Semantic Scholar API
S2_BASE = "https://api.semanticscholar.org/graph/v1/paper"
S2_FIELDS = (
    "citationCount,referenceCount,influentialCitationCount,"
    "s2FieldsOfStudy,tldr,openAccessPdf,venue,publicationVenue,externalIds"
)
S2_DELAY = 1.0  # seconds between requests (conservative)

# CrossRef API
CR_BASE = "https://api.crossref.org/works"
CR_USER_AGENT = "ResearchPipeline/1.0 (mailto:gptprojectmanager@gmail.com)"
CR_DELAY = 0.1  # seconds between requests (polite pool)

# DataCite DOI prefix (arXiv-assigned, NOT in CrossRef)
DATACITE_PREFIX = "10.48550"

# Default max results
DEFAULT_MAX_RESULTS = int(os.environ.get("RP_DISCOVERY_MAX_RESULTS", "50"))

# Discovery sources (comma-separated)
DEFAULT_SOURCES = os.environ.get("RP_DISCOVERY_SOURCES", "arxiv")

VALID_SOURCES = {"arxiv", "openalex"}


def extract_arxiv_id(result: arxiv.Result) -> str:
    """Extract clean arxiv_id from an arxiv.Result, stripping version suffix.

    Args:
        result: An arxiv.Result object.

    Returns:
        Clean arxiv_id (e.g. '2107.05580' not '2107.05580v2').
    """
    entry_id = result.entry_id  # e.g. 'http://arxiv.org/abs/2107.05580v2'
    raw_id = entry_id.rsplit("/", 1)[-1]
    return re.sub(r"v\d+$", "", raw_id)


def search_arxiv(query: str, max_results: int) -> list[dict[str, Any]]:
    """Search arXiv and return paper dicts ready for DB insert.

    Uses arxiv.Client with built-in rate limiting (3s delay) and retries.
    Filters out DataCite DOIs (prefix 10.48550) since CrossRef doesn't have them.

    Args:
        query: arXiv search query (e.g. 'abs:"Kelly criterion" AND cat:q-fin.*').
        max_results: Maximum number of results to return.

    Returns:
        List of paper dicts with fields matching the papers table schema.
    """
    client = arxiv.Client(delay_seconds=3.0, num_retries=3)
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )

    papers: list[dict[str, Any]] = []
    for result in client.results(search):
        arxiv_id = extract_arxiv_id(result)

        # Filter out DataCite DOIs — CrossRef won't have them
        doi = result.doi
        if doi and doi.startswith(DATACITE_PREFIX):
            doi = None

        authors = [a.name for a in result.authors]
        categories = list(result.categories)

        paper = {
            "arxiv_id": arxiv_id,
            "title": result.title,
            "abstract": result.summary,
            "authors": json.dumps(authors),
            "categories": json.dumps(categories),
            "doi": doi,
            "pdf_url": result.pdf_url,
            "published_date": result.published.isoformat() if result.published else None,
            "stage": "discovered",
        }
        papers.append(paper)

    return papers


def enrich_s2(arxiv_id: str) -> dict[str, Any] | None:
    """Enrich a paper with Semantic Scholar metadata.

    Looks up paper by ARXIV:{id}. One retry on 429 with Retry-After.

    Args:
        arxiv_id: Clean arXiv ID (e.g. '2107.05580').

    Returns:
        Enrichment dict or None if lookup failed.
    """
    url = f"{S2_BASE}/ARXIV:{arxiv_id}"
    params = {"fields": S2_FIELDS}

    for attempt in range(2):
        try:
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                enrichment: dict[str, Any] = {
                    "semantic_scholar_id": data.get("paperId"),
                    "citation_count": data.get("citationCount", 0),
                    "reference_count": data.get("referenceCount", 0),
                    "influential_citation_count": data.get("influentialCitationCount", 0),
                    "venue": data.get("venue", ""),
                    "fields_of_study": json.dumps(
                        [f["category"] for f in (data.get("s2FieldsOfStudy") or [])]
                    ),
                    "tldr": data.get("tldr", {}).get("text") if data.get("tldr") else None,
                    "open_access": 1 if data.get("openAccessPdf") else 0,
                }
                # Try to get journal DOI from S2 externalIds
                ext_ids = data.get("externalIds") or {}
                if ext_ids.get("DOI") and not ext_ids["DOI"].startswith(DATACITE_PREFIX):
                    enrichment["doi"] = ext_ids["DOI"]
                return enrichment

            if resp.status_code == 429 and attempt == 0:
                retry_after = int(resp.headers.get("Retry-After", "5"))
                logger.warning("S2 rate limited, retrying in %ds", retry_after)
                time.sleep(retry_after)
                continue

            if resp.status_code == 404:
                logger.info("S2 paper not found: ARXIV:%s", arxiv_id)
                return None

            logger.warning("S2 error %d for ARXIV:%s", resp.status_code, arxiv_id)
            return None

        except requests.RequestException as e:
            logger.warning("S2 request failed for ARXIV:%s: %s", arxiv_id, e)
            return None

    return None


def enrich_crossref(doi: str) -> dict[str, Any] | None:
    """Enrich a paper with CrossRef metadata.

    Looks up by DOI. Only call for journal DOIs (not DataCite/arXiv).

    Args:
        doi: Journal DOI string.

    Returns:
        CrossRef message dict or None if lookup failed.
    """
    url = f"{CR_BASE}/{doi}"
    headers = {"User-Agent": CR_USER_AGENT}

    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("message")

        if resp.status_code == 404:
            logger.info("CrossRef not found for DOI: %s", doi)
            return None

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "5"))
            logger.warning("CrossRef rate limited, waiting %ds", retry_after)
            time.sleep(retry_after)
            # Single retry
            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code == 200:
                return resp.json().get("message")

        logger.warning("CrossRef error %d for DOI: %s", resp.status_code, doi)
        return None

    except requests.RequestException as e:
        logger.warning("CrossRef request failed for DOI %s: %s", doi, e)
        return None


def upsert_paper(db_path: str, paper: dict[str, Any]) -> int | None:
    """Insert or update a paper in the database.

    Uses ON CONFLICT(arxiv_id) DO UPDATE to always return paper_id.
    New papers get inserted; existing papers get their metadata updated.

    Args:
        db_path: Path to SQLite database.
        paper: Paper dict with fields matching papers table columns.

    Returns:
        paper_id (integer) or None on error.
    """
    columns = [
        "arxiv_id", "title", "abstract", "authors", "categories",
        "doi", "pdf_url", "published_date", "source", "stage",
    ]
    # Default source to 'arxiv' for backward compat
    if "source" not in paper:
        paper = {**paper, "source": "arxiv"}
    values = [paper.get(col) for col in columns]
    placeholders = ", ".join(["?"] * len(columns))
    col_names = ", ".join(columns)

    # On conflict, update mutable fields (not arxiv_id, not created_at)
    update_cols = ["title", "abstract", "authors", "categories", "doi",
                   "pdf_url", "published_date", "updated_at"]
    update_clause = ", ".join(
        f"{c}=excluded.{c}" if c != "updated_at"
        else "updated_at=datetime('now')"
        for c in update_cols
    )

    sql = (
        f"INSERT INTO papers ({col_names}) VALUES ({placeholders}) "
        f"ON CONFLICT(arxiv_id) DO UPDATE SET {update_clause} "
        f"RETURNING id"
    )

    try:
        with transaction(db_path) as conn:
            cursor = conn.execute(sql, values)
            row = cursor.fetchone()
            return row[0] if row else None
    except Exception as e:
        logger.error("Failed to upsert paper %s: %s", paper.get("arxiv_id"), e)
        return None


def update_paper_s2(db_path: str, paper_id: int, enrichment: dict[str, Any]) -> bool:
    """Update a paper with Semantic Scholar enrichment data.

    Args:
        db_path: Path to SQLite database.
        paper_id: Paper ID to update.
        enrichment: Dict with S2 fields.

    Returns:
        True if updated successfully.
    """
    columns = [
        "semantic_scholar_id", "citation_count", "reference_count",
        "influential_citation_count", "venue", "fields_of_study",
        "tldr", "open_access",
    ]
    # Include doi if S2 found a journal DOI
    if "doi" in enrichment:
        columns.append("doi")

    set_clause = ", ".join(f"{c}=?" for c in columns)
    set_clause += ", updated_at=datetime('now')"
    values = [enrichment.get(c) for c in columns]
    values.append(paper_id)

    try:
        with transaction(db_path) as conn:
            conn.execute(
                f"UPDATE papers SET {set_clause} WHERE id=?",
                values,
            )
        return True
    except Exception as e:
        logger.error("Failed to update S2 for paper %d: %s", paper_id, e)
        return False


def update_paper_crossref(db_path: str, paper_id: int, crossref_data: dict) -> bool:
    """Update a paper with CrossRef data (full JSON blob).

    Args:
        db_path: Path to SQLite database.
        paper_id: Paper ID to update.
        crossref_data: Full CrossRef message dict.

    Returns:
        True if updated successfully.
    """
    try:
        with transaction(db_path) as conn:
            conn.execute(
                "UPDATE papers SET crossref_data=?, updated_at=datetime('now') WHERE id=?",
                (json.dumps(crossref_data), paper_id),
            )
        return True
    except Exception as e:
        logger.error("Failed to update CrossRef for paper %d: %s", paper_id, e)
        return False


class DiscoveryHandler(BaseHandler):
    """Handler for the Discovery service.

    Endpoints:
        POST /process — Search arXiv and enrich papers with S2 + CrossRef.
    """

    @route("POST", "/process")
    def handle_process(self, data: dict) -> dict:
        """Discover and enrich papers from arXiv and/or OpenAlex.

        Request body:
            {
                "query": "abs:\"Kelly criterion\" AND cat:q-fin.*",
                "max_results": 50,
                "sources": ["arxiv", "openalex"]  // optional, defaults to env var
            }

        Returns:
            Summary dict with counts of found, new, enriched papers.
        """
        start = time.time()

        # Validate input
        query = data.get("query")
        if not query or not isinstance(query, str):
            self.send_error_json("'query' is required and must be a string", "VALIDATION_ERROR", 422)
            return None  # type: ignore[return-value]

        max_results = data.get("max_results", DEFAULT_MAX_RESULTS)
        if not isinstance(max_results, int) or max_results < 1 or max_results > 500:
            self.send_error_json("'max_results' must be integer 1-500", "VALIDATION_ERROR", 422)
            return None  # type: ignore[return-value]

        # Parse sources
        sources_raw = data.get("sources") or [
            s.strip() for s in DEFAULT_SOURCES.split(",") if s.strip()
        ]
        if isinstance(sources_raw, str):
            sources_raw = [s.strip() for s in sources_raw.split(",") if s.strip()]
        sources: list[str] = [s for s in sources_raw if s in VALID_SOURCES]
        if not sources:
            self.send_error_json(
                f"'sources' must contain at least one of: {', '.join(VALID_SOURCES)}",
                "VALIDATION_ERROR", 422,
            )
            return None  # type: ignore[return-value]

        assert self.db_path is not None, "db_path must be set"
        db_path: str = self.db_path
        errors: list[str] = []
        papers_new = 0
        papers_enriched_s2 = 0
        papers_enriched_cr = 0
        total_found = 0

        # --- arXiv source ---
        if "arxiv" in sources:
            logger.info("Searching arXiv: query=%r max_results=%d", query, max_results)
            try:
                papers = search_arxiv(query, max_results)
            except Exception as e:
                logger.error("arXiv search failed: %s", e)
                errors.append(f"arXiv search failed: {e}")
                papers = []

            logger.info("arXiv returned %d papers", len(papers))
            total_found += len(papers)

            for paper in papers:
                arxiv_id = paper["arxiv_id"]

                paper_id = upsert_paper(db_path, paper)
                if paper_id is None:
                    errors.append(f"DB upsert failed: {arxiv_id}")
                    continue

                # Track new vs updated
                try:
                    with transaction(db_path) as conn:
                        row = conn.execute(
                            "SELECT created_at, updated_at FROM papers WHERE id=?",
                            (paper_id,),
                        ).fetchone()
                        if row and row["created_at"] == row["updated_at"]:
                            papers_new += 1
                except Exception:
                    pass

                # Enrich with Semantic Scholar
                s2_data: dict[str, Any] | None = None
                try:
                    s2_data = enrich_s2(arxiv_id)
                    if s2_data:
                        if update_paper_s2(db_path, paper_id, s2_data):
                            papers_enriched_s2 += 1
                    time.sleep(S2_DELAY)
                except Exception as e:
                    errors.append(f"S2 enrichment failed for {arxiv_id}: {e}")
                    logger.warning("S2 enrichment error for %s: %s", arxiv_id, e)

                # Enrich with CrossRef (only if journal DOI available)
                doi = paper.get("doi")
                if not doi and s2_data and "doi" in s2_data:
                    doi = s2_data["doi"]

                if doi:
                    try:
                        cr_data = enrich_crossref(doi)
                        if cr_data:
                            if update_paper_crossref(db_path, paper_id, cr_data):
                                papers_enriched_cr += 1
                        time.sleep(CR_DELAY)
                    except Exception as e:
                        errors.append(f"CrossRef enrichment failed for {arxiv_id}: {e}")
                        logger.warning("CrossRef enrichment error for %s: %s", arxiv_id, e)

        # --- OpenAlex source ---
        if "openalex" in sources:
            from services.discovery.openalex import search_openalex, upsert_openalex_paper

            logger.info("Searching OpenAlex: query=%r max_results=%d", query, max_results)
            try:
                oa_papers = search_openalex(query, max_results)
            except Exception as e:
                logger.error("OpenAlex search failed: %s", e)
                errors.append(f"OpenAlex search failed: {e}")
                oa_papers = []

            logger.info("OpenAlex returned %d papers", len(oa_papers))
            total_found += len(oa_papers)

            for paper in oa_papers:
                oa_id = paper.get("openalex_id", "?")
                paper_id = upsert_openalex_paper(db_path, paper)
                if paper_id is None:
                    errors.append(f"DB upsert failed: {oa_id}")
                    continue

                try:
                    with transaction(db_path) as conn:
                        row = conn.execute(
                            "SELECT created_at, updated_at FROM papers WHERE id=?",
                            (paper_id,),
                        ).fetchone()
                        if row and row["created_at"] == row["updated_at"]:
                            papers_new += 1
                except Exception:
                    pass

        elapsed_ms = int((time.time() - start) * 1000)
        logger.info(
            "Discovery complete: sources=%s found=%d new=%d s2=%d cr=%d errors=%d time=%dms",
            sources, total_found, papers_new, papers_enriched_s2, papers_enriched_cr,
            len(errors), elapsed_ms,
        )

        return {
            "sources": sources,
            "papers_found": total_found,
            "papers_new": papers_new,
            "papers_enriched_s2": papers_enriched_s2,
            "papers_enriched_cr": papers_enriched_cr,
            "errors": errors,
            "time_ms": elapsed_ms,
        }


def main() -> None:
    """Start the Discovery service."""
    config = load_config("discovery")
    init_db(config.db_path)

    service = BaseService("discovery", config.port, DiscoveryHandler, str(config.db_path))
    service.run()


if __name__ == "__main__":
    main()
