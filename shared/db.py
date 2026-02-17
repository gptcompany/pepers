"""SQLite database layer for the research pipeline.

Provides connection management with WAL mode and foreign keys enabled.
All services share the same database file via this module.

Usage:
    from shared.db import get_connection, init_db

    # Initialize database (creates tables if needed)
    init_db("/path/to/research.db")

    # Get a connection (context manager for auto-commit/rollback)
    with transaction("/path/to/research.db") as conn:
        cursor = conn.execute("SELECT * FROM papers")
        rows = cursor.fetchall()

Design decisions:
- WAL mode for concurrent read access (orchestrator reads while service writes)
- Foreign keys enforced at connection level
- Row factory returns sqlite3.Row for dict-like access
- Single connection per request (no pool needed for ~10 papers/day batch)
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

logger = logging.getLogger(__name__)


SCHEMA = """
-- schema_version table for migration tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- papers: academic paper metadata (Discovery service)
CREATE TABLE IF NOT EXISTS papers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    arxiv_id TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    abstract TEXT,
    authors TEXT,
    categories TEXT,
    doi TEXT,
    pdf_url TEXT,
    published_date TEXT,
    semantic_scholar_id TEXT,
    citation_count INTEGER DEFAULT 0,
    reference_count INTEGER DEFAULT 0,
    influential_citation_count INTEGER DEFAULT 0,
    venue TEXT,
    fields_of_study TEXT,
    tldr TEXT,
    open_access INTEGER DEFAULT 0,
    crossref_data TEXT,
    stage TEXT NOT NULL DEFAULT 'discovered',
    score REAL,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- formulas: extracted LaTeX formulas (Extractor service)
CREATE TABLE IF NOT EXISTS formulas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER NOT NULL REFERENCES papers(id),
    latex TEXT NOT NULL,
    latex_hash TEXT NOT NULL,
    description TEXT,
    formula_type TEXT,
    context TEXT,
    stage TEXT NOT NULL DEFAULT 'extracted',
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(paper_id, latex_hash)
);

-- validations: CAS validation results (Validator service)
CREATE TABLE IF NOT EXISTS validations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    formula_id INTEGER NOT NULL REFERENCES formulas(id),
    engine TEXT NOT NULL,
    is_valid INTEGER,
    result TEXT,
    error TEXT,
    time_ms INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- generated_code: code generation results (Codegen service)
CREATE TABLE IF NOT EXISTS generated_code (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    formula_id INTEGER NOT NULL REFERENCES formulas(id),
    language TEXT NOT NULL,
    code TEXT NOT NULL,
    metadata TEXT,
    stage TEXT NOT NULL DEFAULT 'codegen',
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- github_repos: discovered GitHub repositories (GitHub Discovery module)
CREATE TABLE IF NOT EXISTS github_repos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER NOT NULL REFERENCES papers(id),
    full_name TEXT NOT NULL,
    url TEXT NOT NULL,
    clone_url TEXT NOT NULL,
    description TEXT,
    stars INTEGER DEFAULT 0,
    language TEXT,
    updated_at TEXT,
    topics TEXT,
    search_query TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(paper_id, full_name)
);

-- github_analyses: Gemini analysis results per repo
CREATE TABLE IF NOT EXISTS github_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id INTEGER NOT NULL REFERENCES github_repos(id),
    relevance_score INTEGER,
    quality_score INTEGER,
    formula_matches TEXT,
    summary TEXT,
    recommendation TEXT,
    key_files TEXT,
    dependencies TEXT,
    model_used TEXT,
    analysis_time_ms INTEGER,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

INDEXES = """
CREATE INDEX IF NOT EXISTS idx_papers_stage ON papers(stage);
CREATE INDEX IF NOT EXISTS idx_papers_arxiv_id ON papers(arxiv_id);
CREATE INDEX IF NOT EXISTS idx_formulas_paper_id ON formulas(paper_id);
CREATE INDEX IF NOT EXISTS idx_formulas_latex_hash ON formulas(latex_hash);
CREATE INDEX IF NOT EXISTS idx_validations_formula_id ON validations(formula_id);
CREATE INDEX IF NOT EXISTS idx_generated_code_formula_id ON generated_code(formula_id);
CREATE INDEX IF NOT EXISTS idx_github_repos_paper_id ON github_repos(paper_id);
CREATE INDEX IF NOT EXISTS idx_github_repos_full_name ON github_repos(full_name);
CREATE INDEX IF NOT EXISTS idx_github_analyses_repo_id ON github_analyses(repo_id);
CREATE INDEX IF NOT EXISTS idx_github_analyses_recommendation ON github_analyses(recommendation);
"""


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """Create a new SQLite connection with WAL mode and foreign keys.

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        Configured sqlite3.Connection with WAL mode and foreign keys enabled.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def transaction(db_path: str | Path) -> Generator[sqlite3.Connection, None, None]:
    """Context manager that provides a connection with auto-commit/rollback.

    Commits on success, rolls back on exception.

    Args:
        db_path: Path to the SQLite database file.

    Yields:
        sqlite3.Connection within a transaction.
    """
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


MIGRATIONS: dict[int, str] = {
    3: """
    -- v3: Add UNIQUE constraint on (paper_id, latex_hash) to formulas table.
    -- SQLite cannot ALTER TABLE ADD CONSTRAINT, so recreate the table.
    CREATE TABLE IF NOT EXISTS formulas_v3 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        paper_id INTEGER NOT NULL REFERENCES papers(id),
        latex TEXT NOT NULL,
        latex_hash TEXT NOT NULL,
        description TEXT,
        formula_type TEXT,
        context TEXT,
        stage TEXT NOT NULL DEFAULT 'extracted',
        error TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(paper_id, latex_hash)
    );
    INSERT OR IGNORE INTO formulas_v3 (id, paper_id, latex, latex_hash, description, formula_type, context, stage, error, created_at)
        SELECT id, paper_id, latex, latex_hash, description, formula_type, context, stage, error, created_at
        FROM formulas
        GROUP BY paper_id, latex_hash
        HAVING id = MIN(id);
    DROP TABLE formulas;
    ALTER TABLE formulas_v3 RENAME TO formulas;
    -- Recreate indexes lost after table drop
    CREATE INDEX IF NOT EXISTS idx_formulas_paper_id ON formulas(paper_id);
    CREATE INDEX IF NOT EXISTS idx_formulas_latex_hash ON formulas(latex_hash);
    """,
}


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Apply pending schema migrations in order."""
    current = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] or 0
    for version in sorted(MIGRATIONS):
        if version > current:
            logger.info("Applying migration v%d", version)
            conn.executescript(MIGRATIONS[version])
            conn.execute(
                "INSERT OR IGNORE INTO schema_version (version) VALUES (?)",
                (version,),
            )
            conn.commit()
            logger.info("Migration v%d applied", version)


def init_db(db_path: str | Path) -> None:
    """Initialize the database schema and apply pending migrations.

    Creates all tables if they don't exist. Idempotent.

    Args:
        db_path: Path to the SQLite database file.
    """
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.executescript(INDEXES)
        conn.execute("INSERT OR IGNORE INTO schema_version (version) VALUES (1)")
        conn.execute("INSERT OR IGNORE INTO schema_version (version) VALUES (2)")
        conn.commit()
        _run_migrations(conn)
    finally:
        conn.close()
