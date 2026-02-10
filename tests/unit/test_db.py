"""Unit tests for shared/db.py — SQLite connection management."""

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
        assert versions == 1

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
