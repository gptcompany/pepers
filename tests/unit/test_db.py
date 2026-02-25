"""Unit tests for shared/db.py — SQLite connection management + migrations."""

from __future__ import annotations

import sqlite3

import pytest

from shared.db import get_connection, init_db, transaction


class TestGetConnection:
    """Tests for get_connection()."""

    def test_returns_connection(self, tmp_db_path):
        conn = get_connection(tmp_db_path)
        assert isinstance(conn, sqlite3.Connection)
        conn.close()

    def test_wal_mode_enabled(self, tmp_db_path):
        conn = get_connection(tmp_db_path)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"
        conn.close()

    def test_foreign_keys_enabled(self, tmp_db_path):
        conn = get_connection(tmp_db_path)
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1
        conn.close()

    def test_row_factory_set(self, tmp_db_path):
        conn = get_connection(tmp_db_path)
        assert conn.row_factory is sqlite3.Row
        conn.close()

    def test_creates_parent_directory(self, tmp_path):
        nested = tmp_path / "deep" / "nested" / "test.db"
        conn = get_connection(nested)
        assert nested.parent.exists()
        conn.close()

    def test_accepts_string_path(self, tmp_db_path):
        conn = get_connection(str(tmp_db_path))
        assert isinstance(conn, sqlite3.Connection)
        conn.close()


class TestTransaction:
    """Tests for transaction() context manager."""

    def test_commits_on_success(self, tmp_db_path):
        init_db(tmp_db_path)
        with transaction(tmp_db_path) as conn:
            conn.execute(
                "INSERT INTO papers (arxiv_id, title, stage) VALUES (?, ?, ?)",
                ("2401.00001", "Test Paper", "discovered"),
            )
        conn2 = get_connection(tmp_db_path)
        row = conn2.execute(
            "SELECT title FROM papers WHERE arxiv_id=?", ("2401.00001",)
        ).fetchone()
        assert row["title"] == "Test Paper"
        conn2.close()

    def test_rollback_on_exception(self, tmp_db_path):
        init_db(tmp_db_path)
        with pytest.raises(ValueError):
            with transaction(tmp_db_path) as conn:
                conn.execute(
                    "INSERT INTO papers (arxiv_id, title, stage) VALUES (?, ?, ?)",
                    ("2401.00002", "Should Rollback", "discovered"),
                )
                raise ValueError("test error")
        conn2 = get_connection(tmp_db_path)
        row = conn2.execute(
            "SELECT * FROM papers WHERE arxiv_id=?", ("2401.00002",)
        ).fetchone()
        assert row is None
        conn2.close()

    def test_connection_closed_after_use(self, tmp_db_path):
        init_db(tmp_db_path)
        with transaction(tmp_db_path) as conn:
            conn.execute("SELECT 1")
        with pytest.raises(Exception):
            conn.execute("SELECT 1")


class TestInitDb:
    """Tests for init_db()."""

    def test_creates_all_tables(self, tmp_db_path):
        init_db(tmp_db_path)
        conn = get_connection(tmp_db_path)
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
        conn.close()
        assert "papers" in tables
        assert "formulas" in tables
        assert "validations" in tables
        assert "generated_code" in tables
        assert "schema_version" in tables

    def test_creates_all_indexes(self, tmp_db_path):
        init_db(tmp_db_path)
        conn = get_connection(tmp_db_path)
        indexes = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
            ).fetchall()
        ]
        conn.close()
        expected = [
            "idx_papers_stage",
            "idx_papers_arxiv_id",
            "idx_formulas_paper_id",
            "idx_formulas_latex_hash",
            "idx_validations_formula_id",
            "idx_generated_code_formula_id",
        ]
        for idx in expected:
            assert idx in indexes, f"Missing index: {idx}"

    def test_schema_version_set(self, tmp_db_path):
        init_db(tmp_db_path)
        conn = get_connection(tmp_db_path)
        version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
        conn.close()
        assert version == 1

    def test_idempotent(self, tmp_db_path):
        init_db(tmp_db_path)
        init_db(tmp_db_path)
        conn = get_connection(tmp_db_path)
        versions = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
        conn.close()
        assert versions == 6  # v1 + v2 (github) + v3 (UNIQUE) + v4 (pipeline_runs) + v5 (openalex) + v6 (custom_notations)

    def test_foreign_keys_enforced(self, tmp_db_path):
        init_db(tmp_db_path)
        conn = get_connection(tmp_db_path)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO formulas (paper_id, latex, latex_hash, stage) "
                "VALUES (?, ?, ?, ?)",
                (9999, "x^2", "abc123", "extracted"),
            )
        conn.close()

    def test_arxiv_id_unique(self, tmp_db_path):
        init_db(tmp_db_path)
        conn = get_connection(tmp_db_path)
        conn.execute(
            "INSERT INTO papers (arxiv_id, title, stage) VALUES (?, ?, ?)",
            ("2401.00001", "Paper 1", "discovered"),
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO papers (arxiv_id, title, stage) VALUES (?, ?, ?)",
                ("2401.00001", "Duplicate", "discovered"),
            )
        conn.close()


class TestSchemaMigration:
    """Tests for schema migration v2→v3 (UNIQUE constraint on formulas)."""

    def test_fresh_db_has_unique_constraint(self, tmp_db_path):
        """New database should have UNIQUE(paper_id, latex_hash) on formulas."""
        init_db(tmp_db_path)
        conn = get_connection(tmp_db_path)
        schema = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='formulas'"
        ).fetchone()[0]
        conn.close()
        assert "UNIQUE(paper_id, latex_hash)" in schema

    def test_fresh_db_schema_version_6(self, tmp_db_path):
        """New database should be at schema version 6."""
        init_db(tmp_db_path)
        conn = get_connection(tmp_db_path)
        v = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        conn.close()
        assert v == 6

    def test_migration_v2_to_v3(self, tmp_db_path):
        """Existing v2 database should migrate to v3 with UNIQUE constraint."""
        # Create v2-style DB without UNIQUE on formulas (full column set)
        conn = get_connection(tmp_db_path)
        conn.execute(
            "CREATE TABLE schema_version "
            "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        conn.execute("INSERT INTO schema_version (version) VALUES (1)")
        conn.execute("INSERT INTO schema_version (version) VALUES (2)")
        conn.execute(
            "CREATE TABLE papers (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "arxiv_id TEXT UNIQUE NOT NULL, title TEXT NOT NULL, abstract TEXT, "
            "authors TEXT, categories TEXT, doi TEXT, pdf_url TEXT, "
            "published_date TEXT, semantic_scholar_id TEXT, "
            "citation_count INTEGER DEFAULT 0, reference_count INTEGER DEFAULT 0, "
            "influential_citation_count INTEGER DEFAULT 0, venue TEXT, "
            "fields_of_study TEXT, tldr TEXT, open_access INTEGER DEFAULT 0, "
            "crossref_data TEXT, "
            "stage TEXT NOT NULL DEFAULT 'discovered', score REAL, error TEXT, "
            "created_at TEXT NOT NULL DEFAULT (datetime('now')), "
            "updated_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        conn.execute(
            "CREATE TABLE formulas (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "paper_id INTEGER NOT NULL REFERENCES papers(id), "
            "latex TEXT NOT NULL, latex_hash TEXT NOT NULL, "
            "description TEXT, formula_type TEXT, context TEXT, "
            "stage TEXT NOT NULL DEFAULT 'extracted', error TEXT, "
            "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        conn.commit()
        conn.close()

        # Run init_db (triggers migration)
        init_db(tmp_db_path)

        conn = get_connection(tmp_db_path)
        schema = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='formulas'"
        ).fetchone()[0]
        v = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        conn.close()
        assert "UNIQUE" in schema
        assert v == 6

    def test_migration_deduplicates(self, tmp_db_path):
        """Migration should remove duplicate (paper_id, latex_hash) rows."""
        conn = get_connection(tmp_db_path)
        conn.execute(
            "CREATE TABLE schema_version "
            "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        conn.execute("INSERT INTO schema_version (version) VALUES (1)")
        conn.execute("INSERT INTO schema_version (version) VALUES (2)")
        conn.execute(
            "CREATE TABLE papers (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "arxiv_id TEXT UNIQUE NOT NULL, title TEXT NOT NULL, abstract TEXT, "
            "authors TEXT, categories TEXT, doi TEXT, pdf_url TEXT, "
            "published_date TEXT, semantic_scholar_id TEXT, "
            "citation_count INTEGER DEFAULT 0, reference_count INTEGER DEFAULT 0, "
            "influential_citation_count INTEGER DEFAULT 0, venue TEXT, "
            "fields_of_study TEXT, tldr TEXT, open_access INTEGER DEFAULT 0, "
            "crossref_data TEXT, "
            "stage TEXT NOT NULL DEFAULT 'discovered', score REAL, error TEXT, "
            "created_at TEXT NOT NULL DEFAULT (datetime('now')), "
            "updated_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        conn.execute(
            "CREATE TABLE formulas (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "paper_id INTEGER NOT NULL, latex TEXT NOT NULL, "
            "latex_hash TEXT NOT NULL, description TEXT, formula_type TEXT, "
            "context TEXT, stage TEXT NOT NULL DEFAULT 'extracted', error TEXT, "
            "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        conn.execute(
            "INSERT INTO papers (arxiv_id, title, stage) VALUES ('test', 'Test', 'discovered')"
        )
        # Insert duplicates
        conn.execute(
            "INSERT INTO formulas (paper_id, latex, latex_hash, stage) VALUES (1, 'x^2', 'abc', 'extracted')"
        )
        conn.execute(
            "INSERT INTO formulas (paper_id, latex, latex_hash, stage) VALUES (1, 'x^2', 'abc', 'extracted')"
        )
        conn.execute(
            "INSERT INTO formulas (paper_id, latex, latex_hash, stage) VALUES (1, 'y^2', 'def', 'extracted')"
        )
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM formulas").fetchone()[0] == 3
        conn.close()

        init_db(tmp_db_path)

        conn = get_connection(tmp_db_path)
        count = conn.execute("SELECT COUNT(*) FROM formulas").fetchone()[0]
        conn.close()
        assert count == 2  # one duplicate removed

    def test_duplicate_formula_rejected(self, tmp_db_path):
        """After migration, duplicate (paper_id, latex_hash) INSERT raises IntegrityError."""
        init_db(tmp_db_path)
        conn = get_connection(tmp_db_path)
        conn.execute(
            "INSERT INTO papers (arxiv_id, title, stage) VALUES ('test', 'Test', 'discovered')"
        )
        conn.execute(
            "INSERT INTO formulas (paper_id, latex, latex_hash, stage) VALUES (1, 'x^2', 'abc', 'extracted')"
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO formulas (paper_id, latex, latex_hash, stage) VALUES (1, 'x^2', 'abc', 'extracted')"
            )
        conn.close()


class TestSchemaMigrationV5:
    """Tests for schema migration v5 (OpenAlex multi-source)."""

    def test_fresh_db_has_source_column(self, tmp_db_path):
        """New database should have source column on papers."""
        init_db(tmp_db_path)
        conn = get_connection(tmp_db_path)
        schema = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='papers'"
        ).fetchone()[0]
        conn.close()
        assert "source TEXT NOT NULL DEFAULT 'arxiv'" in schema

    def test_fresh_db_has_openalex_id_column(self, tmp_db_path):
        """New database should have openalex_id column on papers."""
        init_db(tmp_db_path)
        conn = get_connection(tmp_db_path)
        schema = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='papers'"
        ).fetchone()[0]
        conn.close()
        assert "openalex_id TEXT UNIQUE" in schema

    def test_fresh_db_arxiv_id_nullable(self, tmp_db_path):
        """New database should allow NULL arxiv_id."""
        init_db(tmp_db_path)
        conn = get_connection(tmp_db_path)
        # Insert paper without arxiv_id
        conn.execute(
            "INSERT INTO papers (title, source, openalex_id, stage) "
            "VALUES ('OA Paper', 'openalex', 'W123', 'discovered')"
        )
        conn.commit()
        row = conn.execute(
            "SELECT arxiv_id, source, openalex_id FROM papers WHERE openalex_id='W123'"
        ).fetchone()
        conn.close()
        assert row["arxiv_id"] is None
        assert row["source"] == "openalex"
        assert row["openalex_id"] == "W123"

    def test_fresh_db_has_openalex_index(self, tmp_db_path):
        """New database should have index on openalex_id."""
        init_db(tmp_db_path)
        conn = get_connection(tmp_db_path)
        indexes = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
            ).fetchall()
        ]
        conn.close()
        assert "idx_papers_openalex_id" in indexes
        assert "idx_papers_source" in indexes

    def test_migration_v4_to_v5(self, tmp_db_path):
        """Existing v4 database should migrate to v5 with source + openalex_id."""
        # Create v4-style DB
        conn = get_connection(tmp_db_path)
        conn.execute(
            "CREATE TABLE schema_version "
            "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        for v in [1, 2, 3, 4]:
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (v,))
        conn.execute(
            "CREATE TABLE papers (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "arxiv_id TEXT UNIQUE NOT NULL, title TEXT NOT NULL, abstract TEXT, "
            "authors TEXT, categories TEXT, doi TEXT, pdf_url TEXT, "
            "published_date TEXT, semantic_scholar_id TEXT, "
            "citation_count INTEGER DEFAULT 0, reference_count INTEGER DEFAULT 0, "
            "influential_citation_count INTEGER DEFAULT 0, venue TEXT, "
            "fields_of_study TEXT, tldr TEXT, open_access INTEGER DEFAULT 0, "
            "crossref_data TEXT, "
            "stage TEXT NOT NULL DEFAULT 'discovered', score REAL, error TEXT, "
            "created_at TEXT NOT NULL DEFAULT (datetime('now')), "
            "updated_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        # Insert a paper before migration
        conn.execute(
            "INSERT INTO papers (arxiv_id, title, stage) VALUES ('2401.00001', 'Existing Paper', 'discovered')"
        )
        conn.commit()
        conn.close()

        # Run init_db (triggers migration v5 + v6)
        init_db(tmp_db_path)

        conn = get_connection(tmp_db_path)
        v = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        assert v == 6

        # Check schema has new columns
        schema = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='papers'"
        ).fetchone()[0]
        assert "source TEXT NOT NULL DEFAULT 'arxiv'" in schema
        assert "openalex_id TEXT UNIQUE" in schema

        # Check existing paper preserved with source='arxiv'
        row = conn.execute(
            "SELECT * FROM papers WHERE arxiv_id='2401.00001'"
        ).fetchone()
        assert row is not None
        assert row["title"] == "Existing Paper"
        assert row["source"] == "arxiv"
        assert row["openalex_id"] is None
        conn.close()

    def test_migration_preserves_all_data(self, tmp_db_path):
        """Migration v5 should preserve all existing paper data."""
        conn = get_connection(tmp_db_path)
        conn.execute(
            "CREATE TABLE schema_version "
            "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        for v in [1, 2, 3, 4]:
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (v,))
        conn.execute(
            "CREATE TABLE papers (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "arxiv_id TEXT UNIQUE NOT NULL, title TEXT NOT NULL, abstract TEXT, "
            "authors TEXT, categories TEXT, doi TEXT, pdf_url TEXT, "
            "published_date TEXT, semantic_scholar_id TEXT, "
            "citation_count INTEGER DEFAULT 0, reference_count INTEGER DEFAULT 0, "
            "influential_citation_count INTEGER DEFAULT 0, venue TEXT, "
            "fields_of_study TEXT, tldr TEXT, open_access INTEGER DEFAULT 0, "
            "crossref_data TEXT, "
            "stage TEXT NOT NULL DEFAULT 'discovered', score REAL, error TEXT, "
            "created_at TEXT NOT NULL DEFAULT (datetime('now')), "
            "updated_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        # Insert multiple papers
        for i in range(5):
            conn.execute(
                "INSERT INTO papers (arxiv_id, title, citation_count, stage) "
                "VALUES (?, ?, ?, 'discovered')",
                (f"2401.{i:05d}", f"Paper {i}", i * 10),
            )
        conn.commit()
        conn.close()

        init_db(tmp_db_path)

        conn = get_connection(tmp_db_path)
        count = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        assert count == 5

        for i in range(5):
            row = conn.execute(
                "SELECT * FROM papers WHERE arxiv_id=?", (f"2401.{i:05d}",)
            ).fetchone()
            assert row["title"] == f"Paper {i}"
            assert row["citation_count"] == i * 10
            assert row["source"] == "arxiv"
        conn.close()
