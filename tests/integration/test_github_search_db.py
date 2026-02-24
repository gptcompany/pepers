"""Integration tests: GitHub Discovery with real SQLite and HTTP server."""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from unittest.mock import patch

import pytest

from shared.db import transaction
from shared.models import GitHubAnalysis, GitHubRepo
from shared.server import BaseService
from services.orchestrator.github_search import (
    _load_paper_context,
    _store_analysis,
    _store_repo,
    search_and_analyze,
)
from services.orchestrator.main import OrchestratorHandler
from services.orchestrator.pipeline import PipelineRunner


def _get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# _store_repo
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStoreRepo:
    """Test _store_repo() with real SQLite."""

    def test_insert_new_repo(self, github_paper_db, sample_github_repo_data):
        db_path = str(github_paper_db)
        with transaction(db_path) as conn:
            repo_id = _store_repo(conn, 1, sample_github_repo_data, "kelly criterion")

        assert repo_id == 1

        with transaction(db_path) as conn:
            row = conn.execute("SELECT * FROM github_repos WHERE id = ?", (repo_id,)).fetchone()

        assert row["full_name"] == "user/kelly-criterion-py"
        assert row["stars"] == 42
        assert row["paper_id"] == 1
        assert row["search_query"] == "kelly criterion"
        assert json.loads(row["topics"]) == ["kelly-criterion", "finance", "portfolio"]

    def test_insert_or_ignore_duplicate(self, github_paper_db, sample_github_repo_data):
        db_path = str(github_paper_db)
        with transaction(db_path) as conn:
            id1 = _store_repo(conn, 1, sample_github_repo_data, "q1")
        with transaction(db_path) as conn:
            id2 = _store_repo(conn, 1, sample_github_repo_data, "q2")

        # Same repo for same paper — returns same ID
        assert id1 == id2

    def test_different_papers_same_repo(self, github_paper_db, sample_github_repo_data):
        db_path = str(github_paper_db)
        # Insert a second paper
        with transaction(db_path) as conn:
            conn.execute(
                "INSERT INTO papers (arxiv_id, title, stage) VALUES (?, ?, ?)",
                ("2401.99999", "Second Paper", "discovered"),
            )

        with transaction(db_path) as conn:
            id1 = _store_repo(conn, 1, sample_github_repo_data, "q1")
        with transaction(db_path) as conn:
            id2 = _store_repo(conn, 2, sample_github_repo_data, "q2")

        # Different papers, different repo rows
        assert id1 != id2


# ---------------------------------------------------------------------------
# _store_analysis
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStoreAnalysis:
    """Test _store_analysis() with real SQLite."""

    def test_insert_analysis(self, github_paper_db, sample_github_repo_data,
                             sample_github_analysis_data):
        db_path = str(github_paper_db)
        with transaction(db_path) as conn:
            repo_id = _store_repo(conn, 1, sample_github_repo_data, "q")
        with transaction(db_path) as conn:
            analysis_id = _store_analysis(
                conn, repo_id, sample_github_analysis_data, "gemini-2.5-pro", 5000
            )

        assert analysis_id >= 1

        with transaction(db_path) as conn:
            row = conn.execute(
                "SELECT * FROM github_analyses WHERE id = ?", (analysis_id,)
            ).fetchone()

        assert row["repo_id"] == repo_id
        assert row["relevance_score"] == 85
        assert row["quality_score"] == 70
        assert row["recommendation"] == "USE"
        assert row["model_used"] == "gemini-2.5-pro"
        assert row["analysis_time_ms"] == 5000
        assert json.loads(row["formula_matches"])[0]["code_file"] == "kelly.py"

    def test_insert_error_analysis(self, github_paper_db, sample_github_repo_data):
        db_path = str(github_paper_db)
        with transaction(db_path) as conn:
            repo_id = _store_repo(conn, 1, sample_github_repo_data, "q")
        with transaction(db_path) as conn:
            analysis_id = _store_analysis(
                conn, repo_id,
                {"error": "Gemini timeout", "recommendation": "SKIP"},
                "gemini-2.5-pro", 0,
            )

        with transaction(db_path) as conn:
            row = conn.execute(
                "SELECT * FROM github_analyses WHERE id = ?", (analysis_id,)
            ).fetchone()

        assert row["error"] == "Gemini timeout"
        assert row["recommendation"] == "SKIP"
        assert row["relevance_score"] is None


# ---------------------------------------------------------------------------
# _load_paper_context
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestLoadPaperContext:
    """Test _load_paper_context() with real DB."""

    def test_loads_paper_with_formulas(self, github_paper_db):
        db_path = str(github_paper_db)
        with transaction(db_path) as conn:
            ctx = _load_paper_context(conn, 1)

        assert ctx is not None
        assert ctx["title"] == "Kelly Criterion in Portfolio Optimization"
        assert len(ctx["formulas"]) == 1
        assert ctx["formulas"][0]["latex"] == r"f^* = \frac{p}{a} - \frac{q}{b}"

    def test_nonexistent_paper(self, github_paper_db):
        db_path = str(github_paper_db)
        with transaction(db_path) as conn:
            ctx = _load_paper_context(conn, 999)

        assert ctx is None

    def test_paper_without_formulas(self, initialized_db):
        db_path = str(initialized_db)
        with transaction(db_path) as conn:
            conn.execute(
                "INSERT INTO papers (arxiv_id, title, stage) VALUES (?, ?, ?)",
                ("2401.00001", "No Formula Paper", "discovered"),
            )

        with transaction(db_path) as conn:
            ctx = _load_paper_context(conn, 1)

        assert ctx is not None
        assert ctx["formulas"] == []


# ---------------------------------------------------------------------------
# search_and_analyze (mocked GitHub + Gemini)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSearchAndAnalyzeMocked:
    """Test search_and_analyze() with mocked external calls."""

    @patch("services.orchestrator.github_search.time.sleep")
    @patch("services.orchestrator.github_search.analyze_with_gemini_cli")
    @patch("services.orchestrator.github_search.cleanup_clone")
    @patch("services.orchestrator.github_search.clone_repo")
    @patch("services.orchestrator.github_search.search_github")
    def test_happy_path(self, mock_search, mock_clone, mock_cleanup, mock_analyze,
                        mock_sleep, github_paper_db, sample_github_repo_data,
                        sample_github_analysis_data, tmp_path):
        mock_search.return_value = [sample_github_repo_data]
        clone_dir = tmp_path / "clone_workspace"
        clone_dir.mkdir()
        mock_clone.return_value = clone_dir / "repo"
        (clone_dir / "repo").mkdir()
        mock_analyze.return_value = sample_github_analysis_data

        db_path = str(github_paper_db)
        result = search_and_analyze(paper_id=1, db_path=db_path, max_repos=1)

        assert result["paper_id"] == 1
        assert result["repos_found"] == 1
        assert result["repos_analyzed"] == 1
        assert len(result["results"]) == 1
        assert result["results"][0]["analysis"]["recommendation"] == "USE"
        assert result["errors"] == []

        # Verify DB records
        with transaction(db_path) as conn:
            repos = conn.execute("SELECT * FROM github_repos").fetchall()
            analyses = conn.execute("SELECT * FROM github_analyses").fetchall()

        assert len(repos) == 1
        assert repos[0]["full_name"] == "user/kelly-criterion-py"
        assert len(analyses) == 1
        assert analyses[0]["relevance_score"] == 85

    @patch("services.orchestrator.github_search.search_github")
    def test_paper_not_found(self, mock_search, github_paper_db):
        result = search_and_analyze(paper_id=999, db_path=str(github_paper_db))

        assert result["repos_found"] == 0
        assert result["repos_analyzed"] == 0
        assert len(result["errors"]) == 1
        assert "not found" in result["errors"][0]

    @patch("services.orchestrator.github_search.search_github")
    def test_skip_existing_results(self, mock_search,
                                   github_paper_db, sample_github_repo_data):
        db_path = str(github_paper_db)
        # Pre-seed a repo
        with transaction(db_path) as conn:
            _store_repo(conn, 1, sample_github_repo_data, "q")

        result = search_and_analyze(paper_id=1, db_path=db_path, force=False)

        assert result.get("skipped") is True
        mock_search.assert_not_called()

    @patch("services.orchestrator.github_search.time.sleep")
    @patch("services.orchestrator.github_search.analyze_with_gemini_cli")
    @patch("services.orchestrator.github_search.cleanup_clone")
    @patch("services.orchestrator.github_search.clone_repo")
    @patch("services.orchestrator.github_search.search_github")
    def test_force_re_analyze(self, mock_search, mock_clone, mock_cleanup,
                              mock_analyze, mock_sleep, github_paper_db,
                              sample_github_repo_data,
                              sample_github_analysis_data, tmp_path):
        db_path = str(github_paper_db)
        # Pre-seed a repo
        with transaction(db_path) as conn:
            _store_repo(conn, 1, sample_github_repo_data, "q")

        mock_search.return_value = [sample_github_repo_data]
        clone_dir = tmp_path / "clone_workspace"
        clone_dir.mkdir()
        mock_clone.return_value = clone_dir / "repo"
        (clone_dir / "repo").mkdir()
        mock_analyze.return_value = sample_github_analysis_data

        result = search_and_analyze(paper_id=1, db_path=db_path, force=True)

        assert result.get("skipped") is not True
        assert result["repos_analyzed"] == 1

    @patch("services.orchestrator.github_search.time.sleep")
    @patch("services.orchestrator.github_search.analyze_with_gemini_cli")
    @patch("services.orchestrator.github_search.cleanup_clone")
    @patch("services.orchestrator.github_search.clone_repo")
    @patch("services.orchestrator.github_search.search_github")
    def test_analysis_failure_stored_as_error(self, mock_search, mock_clone,
                                              mock_cleanup, mock_analyze,
                                              mock_sleep, github_paper_db,
                                              sample_github_repo_data, tmp_path):
        mock_search.return_value = [sample_github_repo_data]
        clone_dir = tmp_path / "clone_workspace"
        clone_dir.mkdir()
        mock_clone.return_value = clone_dir / "repo"
        (clone_dir / "repo").mkdir()
        mock_analyze.side_effect = RuntimeError("Gemini exploded")

        db_path = str(github_paper_db)
        result = search_and_analyze(paper_id=1, db_path=db_path, max_repos=1)

        assert result["repos_analyzed"] == 0
        assert len(result["errors"]) == 1
        assert "Gemini exploded" in result["errors"][0]

        # Error should be stored in DB
        with transaction(db_path) as conn:
            analyses = conn.execute("SELECT * FROM github_analyses").fetchall()
        assert len(analyses) == 1
        assert analyses[0]["error"] == "Gemini exploded"

    @patch("services.orchestrator.github_search.search_github")
    def test_no_repos_found(self, mock_search, github_paper_db):
        mock_search.return_value = []
        result = search_and_analyze(paper_id=1, db_path=str(github_paper_db))

        assert result["repos_found"] == 0
        assert result["repos_analyzed"] == 0
        assert result["errors"] == []


# ---------------------------------------------------------------------------
# HTTP endpoint tests: POST /search-github
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSearchGitHubEndpoint:
    """Test POST /search-github HTTP endpoint."""

    @pytest.fixture(autouse=True)
    def setup(self, github_paper_db):
        self.db_path = str(github_paper_db)
        self.port = _get_free_port()

        runner = PipelineRunner(self.db_path)
        OrchestratorHandler.runner = runner

        self.service = BaseService(
            "orchestrator", self.port, OrchestratorHandler, self.db_path
        )
        self.thread = threading.Thread(target=self.service.run, daemon=True)
        self.thread.start()
        time.sleep(0.3)
        yield
        if self.service.server:
            self.service.server.shutdown()
        OrchestratorHandler.runner = None
        OrchestratorHandler._routes = None

    def _post(self, path: str, data: dict) -> dict:
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            f"http://localhost:{self.port}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req)
        return json.loads(resp.read())

    def test_missing_paper_id(self):
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            self._post("/search-github", {})
        assert exc_info.value.code == 400

    def test_invalid_paper_id_type(self):
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            self._post("/search-github", {"paper_id": "not_int"})
        assert exc_info.value.code == 400

    @patch("services.orchestrator.github_search.time.sleep")
    @patch("services.orchestrator.github_search.analyze_with_gemini_cli")
    @patch("services.orchestrator.github_search.cleanup_clone")
    @patch("services.orchestrator.github_search.clone_repo")
    @patch("services.orchestrator.github_search.search_github")
    def test_happy_path(self, mock_search, mock_clone, mock_cleanup,
                        mock_analyze, mock_sleep, sample_github_repo_data,
                        sample_github_analysis_data, tmp_path):
        mock_search.return_value = [sample_github_repo_data]
        clone_dir = tmp_path / "clone_workspace"
        clone_dir.mkdir()
        mock_clone.return_value = clone_dir / "repo"
        (clone_dir / "repo").mkdir()
        mock_analyze.return_value = sample_github_analysis_data

        result = self._post("/search-github", {"paper_id": 1, "max_repos": 1})

        assert result["paper_id"] == 1
        assert result["repos_analyzed"] == 1

    @patch("services.orchestrator.github_search.search_github")
    def test_paper_not_found(self, mock_search):
        result = self._post("/search-github", {"paper_id": 999})
        assert result["repos_found"] == 0
        assert "not found" in result["errors"][0]


# ---------------------------------------------------------------------------
# HTTP endpoint tests: GET /github-repos
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGitHubReposEndpoint:
    """Test GET /github-repos HTTP endpoint."""

    @pytest.fixture(autouse=True)
    def setup(self, github_paper_db, sample_github_repo_data,
              sample_github_analysis_data):
        self.db_path = str(github_paper_db)
        self.port = _get_free_port()

        # Seed repo + analysis
        with transaction(self.db_path) as conn:
            repo_id = _store_repo(conn, 1, sample_github_repo_data, "kelly criterion")
        with transaction(self.db_path) as conn:
            _store_analysis(conn, repo_id, sample_github_analysis_data,
                            "gemini-2.5-pro", 5000)

        runner = PipelineRunner(self.db_path)
        OrchestratorHandler.runner = runner

        self.service = BaseService(
            "orchestrator", self.port, OrchestratorHandler, self.db_path
        )
        self.thread = threading.Thread(target=self.service.run, daemon=True)
        self.thread.start()
        time.sleep(0.3)
        yield
        if self.service.server:
            self.service.server.shutdown()
        OrchestratorHandler.runner = None
        OrchestratorHandler._routes = None

    def _get(self, path: str) -> dict | list:
        resp = urllib.request.urlopen(f"http://localhost:{self.port}{path}")
        return json.loads(resp.read())

    def test_missing_paper_id(self):
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            self._get("/github-repos")
        assert exc_info.value.code == 400

    def test_list_repos_for_paper(self):
        data = self._get("/github-repos?paper_id=1")
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["repo"]["full_name"] == "user/kelly-criterion-py"
        assert data[0]["analysis"]["recommendation"] == "USE"

    def test_filter_by_recommendation(self):
        data = self._get("/github-repos?paper_id=1&recommendation=USE")
        assert len(data) == 1

        data = self._get("/github-repos?paper_id=1&recommendation=SKIP")
        assert len(data) == 0

    def test_limit(self):
        data = self._get("/github-repos?paper_id=1&limit=1")
        assert len(data) <= 1

    def test_empty_result(self):
        data = self._get("/github-repos?paper_id=999")
        assert data == []


# ---------------------------------------------------------------------------
# Pydantic model tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGitHubModels:
    """Test Pydantic models for GitHub Discovery."""

    def test_github_repo_from_db_row(self):
        repo = GitHubRepo(
            id=1,
            paper_id=1,
            full_name="user/repo",
            url="https://github.com/user/repo",
            clone_url="https://github.com/user/repo.git",
            stars=10,
            topics='["topic1", "topic2"]',
        )
        assert repo.topics == ["topic1", "topic2"]
        dumped = repo.model_dump(mode="json")
        assert dumped["topics"] == ["topic1", "topic2"]

    def test_github_analysis_json_fields(self):
        analysis = GitHubAnalysis(
            id=1,
            repo_id=1,
            relevance_score=90,
            formula_matches='[{"formula": "x"}]',
            key_files='["main.py"]',
            dependencies='["numpy"]',
            recommendation="USE",
        )
        assert analysis.formula_matches == [{"formula": "x"}]
        assert analysis.key_files == ["main.py"]
        assert analysis.dependencies == ["numpy"]

    def test_github_analysis_none_scores(self):
        analysis = GitHubAnalysis(
            id=1,
            repo_id=1,
            error="timeout",
        )
        assert analysis.relevance_score is None
        assert analysis.quality_score is None
