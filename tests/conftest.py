"""Shared test fixtures for the research pipeline test suite."""

from __future__ import annotations

import json
import os
import sqlite3

import pytest

from shared.db import init_db, SCHEMA, INDEXES


@pytest.fixture
def memory_db():
    """In-memory SQLite database with schema initialized."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.executescript(INDEXES)
    conn.execute("INSERT OR IGNORE INTO schema_version (version) VALUES (1)")
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def tmp_db_path(tmp_path):
    """Temporary SQLite database file path."""
    return tmp_path / "test_research.db"


@pytest.fixture
def initialized_db(tmp_db_path):
    """Temporary SQLite database file with schema initialized."""
    init_db(tmp_db_path)
    return tmp_db_path


@pytest.fixture
def clean_env():
    """Remove all RP_ env vars before test, restore after."""
    saved = {}
    for key in list(os.environ):
        if key.startswith("RP_"):
            saved[key] = os.environ.pop(key)
    yield
    for key in list(os.environ):
        if key.startswith("RP_"):
            del os.environ[key]
    os.environ.update(saved)


@pytest.fixture
def sample_paper_row():
    """Sample paper data as a dict (mimics INSERT values)."""
    return {
        "arxiv_id": "2401.00001",
        "title": "Kelly Criterion in Portfolio Optimization",
        "abstract": "We study the Kelly criterion for optimal bet sizing.",
        "authors": json.dumps(["Alice Smith", "Bob Jones"]),
        "categories": json.dumps(["q-fin.PM", "stat.ML"]),
        "doi": "10.1234/test.2024.001",
        "pdf_url": "https://arxiv.org/pdf/2401.00001",
        "published_date": "2024-01-15",
        "stage": "discovered",
    }


@pytest.fixture
def sample_formula_data():
    """Sample formula data."""
    return {
        "paper_id": 1,
        "latex": r"f^* = \frac{p}{a} - \frac{q}{b}",
        "description": "Kelly criterion optimal fraction",
        "formula_type": "equation",
    }


@pytest.fixture
def sample_arxiv_result():
    """Mock arxiv.Result object for testing."""
    from unittest.mock import MagicMock
    from datetime import datetime, timezone

    result = MagicMock()
    result.entry_id = "http://arxiv.org/abs/2401.00001v2"
    result.title = "Kelly Criterion in Portfolio Optimization"
    result.summary = "We study the Kelly criterion for optimal bet sizing."
    result.doi = "10.1234/test.2024.001"
    result.pdf_url = "https://arxiv.org/pdf/2401.00001"
    result.published = datetime(2024, 1, 15, tzinfo=timezone.utc)
    result.categories = {"q-fin.PM", "stat.ML"}

    author1 = MagicMock()
    author1.name = "Alice Smith"
    author2 = MagicMock()
    author2.name = "Bob Jones"
    result.authors = [author1, author2]

    return result


@pytest.fixture
def sample_s2_response():
    """Sample Semantic Scholar API response dict."""
    return {
        "paperId": "abc123def456",
        "citationCount": 42,
        "referenceCount": 15,
        "influentialCitationCount": 5,
        "venue": "Journal of Finance",
        "s2FieldsOfStudy": [
            {"category": "Economics"},
            {"category": "Mathematics"},
        ],
        "tldr": {"text": "This paper studies the Kelly criterion."},
        "openAccessPdf": {"url": "https://example.com/paper.pdf"},
        "externalIds": {"DOI": "10.1234/test.2024.001", "ArXiv": "2401.00001"},
        "publicationVenue": {"name": "Journal of Finance"},
    }


@pytest.fixture
def sample_crossref_response():
    """Sample CrossRef API response dict."""
    return {
        "status": "ok",
        "message": {
            "DOI": "10.1234/test.2024.001",
            "title": ["Kelly Criterion in Portfolio Optimization"],
            "author": [
                {"given": "Alice", "family": "Smith"},
                {"given": "Bob", "family": "Jones"},
            ],
            "container-title": ["Journal of Finance"],
            "published-print": {"date-parts": [[2024, 1, 15]]},
            "is-referenced-by-count": 42,
            "type": "journal-article",
        },
    }


# ---------------------------------------------------------------------------
# Analyzer service fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_llm_scores():
    """Valid LLM scoring response as dict (above threshold)."""
    return {
        "scores": {
            "kelly_relevance": 0.85,
            "mathematical_rigor": 0.70,
            "novelty": 0.60,
            "practical_applicability": 0.75,
            "data_quality": 0.65,
        },
        "reasoning": "Relevant paper on Kelly criterion with solid math.",
    }


@pytest.fixture
def sample_llm_response_json(sample_llm_scores):
    """Valid LLM JSON response string."""
    return json.dumps(sample_llm_scores)


@pytest.fixture
def sample_low_score_response():
    """LLM response with below-threshold scores."""
    return json.dumps({
        "scores": {
            "kelly_relevance": 0.2,
            "mathematical_rigor": 0.3,
            "novelty": 0.1,
            "practical_applicability": 0.2,
            "data_quality": 0.3,
        },
        "reasoning": "Paper not related to Kelly criterion.",
    })


@pytest.fixture
def discovered_paper_db(initialized_db, sample_paper_row):
    """DB with one discovered paper ready for analysis, migration applied."""
    from services.discovery.main import upsert_paper
    from services.analyzer.main import migrate_db

    upsert_paper(str(initialized_db), sample_paper_row)
    migrate_db(str(initialized_db))
    return initialized_db


@pytest.fixture
def migrated_db(initialized_db):
    """DB with prompt_version migration applied."""
    from services.analyzer.main import migrate_db

    migrate_db(str(initialized_db))
    return initialized_db
