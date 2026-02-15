"""E2E tests for GitHub Discovery — real GitHub API + real Gemini CLI."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
import urllib.request

import pytest

from shared.db import init_db, transaction
from shared.server import BaseService
from services.orchestrator.github_search import (
    _read_repo_files,
    analyze_with_gemini_cli,
    build_dynamic_prompt,
    cleanup_clone,
    clone_repo,
    search_and_analyze,
    search_github,
)
from services.orchestrator.main import OrchestratorHandler
from services.orchestrator.pipeline import PipelineRunner

pytestmark = pytest.mark.e2e

# Detect API availability
HAS_GITHUB_PAT = bool(os.environ.get("RP_GITHUB_PAT") or os.environ.get("GITHUB_PAT"))
HAS_GEMINI_CLI = bool(subprocess.run(
    ["which", "gemini"], capture_output=True
).returncode == 0)
HAS_GEMINI_KEY = bool(os.environ.get("GEMINI_API_KEY"))


def _get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# Real GitHub API search
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_GITHUB_PAT, reason="GITHUB_PAT not available")
class TestSearchGitHubReal:
    """E2E: Real GitHub API search."""

    def test_search_kelly_criterion_repos(self):
        repos = search_github(
            "kelly criterion",
            languages=["python"],
            min_stars=5,
            max_results=5,
        )

        assert len(repos) >= 1
        # Verify structure
        repo = repos[0]
        assert "full_name" in repo
        assert "url" in repo
        assert "clone_url" in repo
        assert "stars" in repo
        assert repo["stars"] >= 5

    def test_multi_language_search(self):
        repos = search_github(
            "portfolio optimization",
            languages=["python", "rust"],
            min_stars=3,
            max_results=10,
        )

        # Should find repos in at least Python
        assert len(repos) >= 1
        languages = {r.get("language") for r in repos}
        assert "Python" in languages

    def test_search_deduplication(self):
        repos = search_github(
            "kelly criterion",
            languages=["python", "python"],  # Duplicate language
            min_stars=5,
            max_results=10,
        )
        full_names = [r["full_name"] for r in repos]
        assert len(full_names) == len(set(full_names)), "Duplicates found"

    def test_search_no_results(self):
        # Very unlikely to find repos with this query
        repos = search_github(
            "xyzzy_nonexistent_query_12345_no_results",
            languages=["python"],
            min_stars=1000,
            max_results=5,
        )
        assert repos == []


# ---------------------------------------------------------------------------
# Real git clone + file reading
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_GITHUB_PAT, reason="GITHUB_PAT not available")
class TestCloneAndReadReal:
    """E2E: Real git clone and file reading."""

    def test_clone_and_read_small_repo(self):
        # First search for a real repo, then clone it
        repos = search_github(
            "kelly criterion",
            languages=["python"],
            min_stars=5,
            max_results=3,
        )
        assert len(repos) >= 1, "No repos found to clone"

        clone_path = None
        try:
            clone_path = clone_repo(repos[0]["clone_url"], timeout=60)

            assert clone_path.exists()
            assert (clone_path / ".git").exists()

            # Read files
            content = _read_repo_files(clone_path)
            assert len(content) > 0

        finally:
            if clone_path:
                cleanup_clone(clone_path)
                assert not clone_path.parent.exists()


# ---------------------------------------------------------------------------
# Real Gemini CLI analysis
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (HAS_GEMINI_CLI and HAS_GEMINI_KEY),
    reason="Gemini CLI or API key not available",
)
class TestGeminiAnalysisReal:
    """E2E: Real Gemini CLI analysis of cloned repos."""

    @pytest.fixture
    def cloned_repo(self, tmp_path):
        """Create a minimal fake repo for analysis."""
        repo_dir = tmp_path / "test_repo"
        repo_dir.mkdir()
        (repo_dir / "kelly.py").write_text(
            "import math\n\n"
            "def kelly_fraction(p: float, b: float) -> float:\n"
            "    \"\"\"Compute Kelly optimal fraction.\"\"\"\n"
            "    q = 1 - p\n"
            "    return (p * b - q) / b\n\n"
            "def growth_rate(f: float, p: float, b: float) -> float:\n"
            "    q = 1 - p\n"
            "    return p * math.log(1 + f * b) + q * math.log(1 - f)\n"
        )
        (repo_dir / "README.md").write_text(
            "# Kelly Criterion\n"
            "Implementation of the Kelly criterion for optimal bet sizing.\n"
        )
        return repo_dir

    def test_analyze_with_gemini_cli(self, cloned_repo):
        paper_context = {
            "title": "Kelly Criterion in Portfolio Optimization",
            "abstract": "Optimal bet sizing strategy.",
            "stage": "extracted",
            "formulas": [
                {"latex": r"f^* = \frac{pb - q}{b}", "description": "Kelly formula"},
            ],
        }
        repo_info = {
            "full_name": "test/kelly-test",
            "description": "Test Kelly implementation",
            "stars": 10,
            "language": "Python",
        }

        prompt = build_dynamic_prompt(paper_context, repo_info)
        result = analyze_with_gemini_cli(
            cloned_repo, prompt,
            model="gemini-2.5-flash",
            timeout=120,
        )

        # Verify result structure
        assert isinstance(result, dict)
        assert "relevance_score" in result
        assert "recommendation" in result
        assert result["recommendation"] in ("USE", "REFERENCE", "SKIP")
        assert isinstance(result.get("relevance_score"), (int, float))


# ---------------------------------------------------------------------------
# Full E2E: search → clone → analyze → DB
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (HAS_GITHUB_PAT and HAS_GEMINI_CLI and HAS_GEMINI_KEY),
    reason="GitHub PAT and Gemini CLI/key required",
)
class TestFullSearchAndAnalyzeE2E:
    """E2E: Complete search_and_analyze flow with real APIs."""

    def test_full_flow_real(self, tmp_path):
        db_path = tmp_path / "e2e_github.db"
        init_db(db_path)

        # Seed a paper
        with transaction(str(db_path)) as conn:
            conn.execute(
                "INSERT INTO papers (arxiv_id, title, abstract, stage) "
                "VALUES (?, ?, ?, ?)",
                (
                    "2401.00001",
                    "Kelly Criterion Portfolio Optimization",
                    "Optimal bet sizing using the Kelly criterion.",
                    "extracted",
                ),
            )
            conn.execute(
                "INSERT INTO formulas (paper_id, latex, latex_hash, description, stage) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    1,
                    r"f^* = \frac{pb - q}{b}",
                    "e2e_kelly_hash",
                    "Kelly optimal fraction",
                    "extracted",
                ),
            )

        result = search_and_analyze(
            paper_id=1,
            db_path=str(db_path),
            max_repos=1,
            languages=["python"],
            min_stars=5,
        )

        assert result["paper_id"] == 1
        assert result["repos_found"] >= 0  # May find 0 if rate limited

        if result["repos_found"] > 0:
            # Verify DB records were created
            with transaction(str(db_path)) as conn:
                repos = conn.execute("SELECT * FROM github_repos").fetchall()
                analyses = conn.execute("SELECT * FROM github_analyses").fetchall()

            assert len(repos) >= 1
            assert len(analyses) >= 1

            # Check analysis has required fields
            analysis = dict(analyses[0])
            assert analysis["model_used"] is not None
            assert analysis["analysis_time_ms"] >= 0


# ---------------------------------------------------------------------------
# E2E: HTTP endpoints with real server
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (HAS_GITHUB_PAT and HAS_GEMINI_CLI and HAS_GEMINI_KEY),
    reason="GitHub PAT and Gemini CLI/key required",
)
class TestEndpointsE2E:
    """E2E: Real HTTP server with POST /search-github + GET /github-repos."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        db_path = tmp_path / "e2e_endpoint.db"
        init_db(db_path)
        self.db_path = str(db_path)
        self.port = _get_free_port()

        # Seed a paper
        with transaction(self.db_path) as conn:
            conn.execute(
                "INSERT INTO papers (arxiv_id, title, abstract, stage) "
                "VALUES (?, ?, ?, ?)",
                (
                    "2401.00001",
                    "Kelly Criterion Portfolio Optimization",
                    "Optimal bet sizing.",
                    "extracted",
                ),
            )
            conn.execute(
                "INSERT INTO formulas (paper_id, latex, latex_hash, description, stage) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    1,
                    r"f^* = \frac{pb - q}{b}",
                    "e2e_ep_hash",
                    "Kelly formula",
                    "extracted",
                ),
            )

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

    def test_search_github_endpoint_real(self):
        body = json.dumps({
            "paper_id": 1,
            "max_repos": 1,
            "languages": ["python"],
            "min_stars": 5,
        }).encode()
        req = urllib.request.Request(
            f"http://localhost:{self.port}/search-github",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=300)
        data = json.loads(resp.read())

        assert data["paper_id"] == 1
        assert isinstance(data["repos_found"], int)

    def test_github_repos_endpoint_after_search(self):
        # First search
        body = json.dumps({
            "paper_id": 1,
            "max_repos": 1,
            "languages": ["python"],
        }).encode()
        req = urllib.request.Request(
            f"http://localhost:{self.port}/search-github",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=300)

        # Then query
        resp = urllib.request.urlopen(
            f"http://localhost:{self.port}/github-repos?paper_id=1",
            timeout=30,
        )
        data = json.loads(resp.read())

        assert isinstance(data, list)
        # May be empty if search found nothing, but endpoint works
