"""OpenAlex API client for multi-source paper discovery.

Searches the OpenAlex database (200M+ works) and maps results to PePeRS
paper format. Provides upsert logic for deduplication with existing arXiv papers.

OpenAlex API docs: https://docs.openalex.org/api-entities/works

Usage:
    from services.discovery.openalex import search_openalex, upsert_openalex_paper

    papers = search_openalex("Kelly criterion portfolio optimization", max_results=50)
    for paper in papers:
        upsert_openalex_paper(db_path, paper)
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import requests

from shared.db import transaction

logger = logging.getLogger(__name__)

# OpenAlex API
OA_BASE = "https://api.openalex.org/works"
OA_MAILTO = os.environ.get("RP_CONTACT_EMAIL", "pepers-bot@users.noreply.github.com")  # polite pool


def _reconstruct_abstract(inverted_index: dict[str, list[int]] | None) -> str | None:
    """Reconstruct abstract text from OpenAlex inverted index format.

    OpenAlex stores abstracts as {"word": [positions]} for compression.
    We reconstruct the original text by placing words at their positions.

    Args:
        inverted_index: OpenAlex abstract_inverted_index field.

    Returns:
        Reconstructed abstract string, or None if input is empty/None.
    """
    if not inverted_index:
        return None

    # Build position -> word mapping
    words: dict[int, str] = {}
    for word, positions in inverted_index.items():
        for pos in positions:
            words[pos] = word

    if not words:
        return None

    # Reconstruct in order
    max_pos = max(words.keys())
    return " ".join(words.get(i, "") for i in range(max_pos + 1))


def _extract_arxiv_id_from_locations(locations: list[dict]) -> str | None:
    """Extract arXiv ID from OpenAlex locations if available.

    Args:
        locations: OpenAlex work locations list.

    Returns:
        Clean arXiv ID (e.g. '2401.00001') or None.
    """
    for loc in locations:
        source = loc.get("source") or {}
        # Check if source is arXiv
        if source.get("display_name", "").lower() == "arxiv":
            landing_url = loc.get("landing_page_url") or ""
            # Extract ID from URL like https://arxiv.org/abs/2401.00001
            match = re.search(r"arxiv\.org/abs/(\d+\.\d+)", landing_url)
            if match:
                return match.group(1)

        # Also check pdf_url for arXiv links
        pdf_url = loc.get("pdf_url") or ""
        match = re.search(r"arxiv\.org/pdf/(\d+\.\d+)", pdf_url)
        if match:
            return match.group(1)

    return None


def _strip_openalex_url(oa_id: str) -> str:
    """Strip OpenAlex URL prefix, returning just the ID.

    Args:
        oa_id: Full OpenAlex ID like 'https://openalex.org/W2741809807'.

    Returns:
        Short ID like 'W2741809807'.
    """
    return oa_id.rsplit("/", 1)[-1] if oa_id else oa_id


def search_openalex(query: str, max_results: int = 50) -> list[dict[str, Any]]:
    """Search OpenAlex and return paper dicts ready for DB insert.

    Uses the polite pool (mailto param) for higher rate limits.

    Args:
        query: Search query string.
        max_results: Maximum number of results to return (max 200 per page).

    Returns:
        List of paper dicts with fields matching the papers table schema.
    """
    params: dict[str, Any] = {
        "search": query,
        "per_page": min(max_results, 200),
        "mailto": OA_MAILTO,
    }

    try:
        resp = requests.get(OA_BASE, params=params, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error("OpenAlex search failed: %s", e)
        raise

    data = resp.json()
    results = data.get("results", [])

    papers: list[dict[str, Any]] = []
    for work in results[:max_results]:
        openalex_id = _strip_openalex_url(work.get("id", ""))
        if not openalex_id:
            continue

        title = work.get("display_name") or work.get("title") or ""
        if not title:
            continue

        # Reconstruct abstract from inverted index
        abstract = _reconstruct_abstract(work.get("abstract_inverted_index"))

        # Extract authors
        authors = []
        for authorship in work.get("authorships", []):
            author = authorship.get("author", {})
            name = author.get("display_name")
            if name:
                authors.append(name)

        # Extract primary topic/field as categories
        categories = []
        primary_topic = work.get("primary_topic") or {}
        field = primary_topic.get("field") or {}
        field_name = field.get("display_name")
        if field_name:
            categories.append(field_name)
        subfield = primary_topic.get("subfield") or {}
        subfield_name = subfield.get("display_name")
        if subfield_name:
            categories.append(subfield_name)

        # Extract DOI (strip URL prefix)
        doi_raw = work.get("doi") or ""
        doi = re.sub(r"^https?://doi\.org/", "", doi_raw) if doi_raw else None

        # PDF URL from open access
        oa = work.get("open_access") or {}
        pdf_url = oa.get("oa_url")

        # Cross-link: extract arxiv_id from locations
        locations = work.get("locations", [])
        arxiv_id = _extract_arxiv_id_from_locations(locations)

        paper: dict[str, Any] = {
            "openalex_id": openalex_id,
            "arxiv_id": arxiv_id,
            "title": title,
            "abstract": abstract,
            "authors": json.dumps(authors),
            "categories": json.dumps(categories),
            "doi": doi,
            "pdf_url": pdf_url,
            "published_date": work.get("publication_date"),
            "citation_count": work.get("cited_by_count", 0),
            "reference_count": work.get("referenced_works_count", 0),
            "source": "openalex",
            "stage": "discovered",
        }
        papers.append(paper)

    logger.info("OpenAlex returned %d papers for query=%r", len(papers), query)
    return papers


def upsert_openalex_paper(db_path: str, paper: dict[str, Any]) -> int | None:
    """Insert or update an OpenAlex paper in the database.

    Uses ON CONFLICT(openalex_id) DO UPDATE. If the paper has an arxiv_id,
    checks for an existing arXiv paper first to avoid duplicates — updates
    the existing row with the openalex_id instead of inserting a new one.

    Args:
        db_path: Path to SQLite database.
        paper: Paper dict from search_openalex().

    Returns:
        paper_id (integer) or None on error.
    """
    openalex_id = paper.get("openalex_id")
    arxiv_id = paper.get("arxiv_id")

    try:
        with transaction(db_path) as conn:
            # Cross-source dedup: if this OpenAlex paper has an arxiv_id,
            # check if we already have it from arXiv discovery
            if arxiv_id:
                existing = conn.execute(
                    "SELECT id FROM papers WHERE arxiv_id=?", (arxiv_id,)
                ).fetchone()
                if existing:
                    # Update existing arXiv paper with OpenAlex data
                    conn.execute(
                        "UPDATE papers SET openalex_id=?, citation_count=?, "
                        "reference_count=?, updated_at=datetime('now') WHERE id=?",
                        (
                            openalex_id,
                            paper.get("citation_count", 0),
                            paper.get("reference_count", 0),
                            existing["id"],
                        ),
                    )
                    return existing["id"]

            # Standard upsert on openalex_id
            columns = [
                "openalex_id", "arxiv_id", "title", "abstract", "authors",
                "categories", "doi", "pdf_url", "published_date",
                "citation_count", "reference_count", "source", "stage",
            ]
            values = [paper.get(col) for col in columns]
            placeholders = ", ".join(["?"] * len(columns))
            col_names = ", ".join(columns)

            update_cols = [
                "title", "abstract", "authors", "categories", "doi",
                "pdf_url", "published_date", "citation_count",
                "reference_count", "updated_at",
            ]
            update_clause = ", ".join(
                f"{c}=excluded.{c}" if c != "updated_at"
                else "updated_at=datetime('now')"
                for c in update_cols
            )

            sql = (
                f"INSERT INTO papers ({col_names}) VALUES ({placeholders}) "
                f"ON CONFLICT(openalex_id) DO UPDATE SET {update_clause} "
                f"RETURNING id"
            )

            cursor = conn.execute(sql, values)
            row = cursor.fetchone()
            return row[0] if row else None

    except Exception as e:
        logger.error("Failed to upsert OpenAlex paper %s: %s", openalex_id, e)
        return None
