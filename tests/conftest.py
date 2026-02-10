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
