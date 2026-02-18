"""Unit tests for shared/db.py — SQLite connection management + migrations."""

from __future__ import annotations

import sqlite3

import pytest

from shared.db import MIGRATIONS, _run_migrations, get_connection, init_db, transaction


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
        assert versions == 4  # v1 + v2 (github) + v3 (UNIQUE) + v4 (pipeline_runs)

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

    def test_fresh_db_schema_version_4(self, tmp_db_path):
        """New database should be at schema version 4."""
        init_db(tmp_db_path)
        conn = get_connection(tmp_db_path)
        v = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        conn.close()
        assert v == 4

    def test_migration_v2_to_v3(self, tmp_db_path):
        """Existing v2 database should migrate to v3 with UNIQUE constraint."""
        # Create v2-style DB without UNIQUE on formulas
        conn = get_connection(tmp_db_path)
        conn.execute(
            "CREATE TABLE schema_version "
            "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        conn.execute("INSERT INTO schema_version (version) VALUES (1)")
        conn.execute("INSERT INTO schema_version (version) VALUES (2)")
        conn.execute(
            "CREATE TABLE papers (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "arxiv_id TEXT UNIQUE NOT NULL, title TEXT NOT NULL, "
            "stage TEXT NOT NULL DEFAULT 'discovered', "
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
        assert v == 4

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
            "arxiv_id TEXT UNIQUE NOT NULL, title TEXT NOT NULL, "
            "stage TEXT NOT NULL DEFAULT 'discovered', "
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
