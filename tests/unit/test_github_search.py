"""Unit tests for GitHub Discovery — pure functions, no external deps."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from services.orchestrator.github_search import (
    EXTENSIONS,
    SKIP_DIRS,
    STOP_WORDS,
    _check_rate_limit,
    _extract_keywords,
    _generate_queries,
    _get_github_headers,
    _parse_json_response,
    _read_repo_files,
    build_dynamic_prompt,
    cleanup_clone,
    clone_repo,
)


# ---------------------------------------------------------------------------
# _extract_keywords
# ---------------------------------------------------------------------------


class TestExtractKeywords:
    """Tests for keyword extraction from paper titles."""

    def test_basic_extraction(self):
        keywords = _extract_keywords("Kelly Criterion Portfolio Optimization")
        assert "Kelly" in keywords
        assert "Criterion" in keywords
        assert "Portfolio" in keywords
        assert "Optimization" in keywords

    def test_stop_words_removed(self):
        keywords = _extract_keywords("The Kelly Criterion for Optimal Bet Sizing")
        lower = [k.lower() for k in keywords]
        for sw in ("the", "for", "optimal"):
            assert sw not in lower

    def test_max_5_keywords(self):
        title = "Alpha Beta Gamma Delta Epsilon Zeta Eta Theta"
        keywords = _extract_keywords(title)
        assert len(keywords) <= 5

    def test_min_length_3(self):
        keywords = _extract_keywords("A Go ML DL Deep Learning")
        lower = [k.lower() for k in keywords]
        assert "go" not in lower
        assert "ml" not in lower
        assert "dl" not in lower
        assert "Deep" in keywords
        assert "Learning" in keywords

    def test_empty_title(self):
        assert _extract_keywords("") == []

    def test_hyphenated_words(self):
        keywords = _extract_keywords("Semi-Supervised Kelly-Criterion Learning")
        # Hyphenated words should be preserved
        assert any("Semi-Supervised" in k for k in keywords)

    def test_stop_words_comprehensive(self):
        title = " ".join(STOP_WORDS)
        keywords = _extract_keywords(title)
        # All stop words should be filtered (those with len > 2)
        assert keywords == []


# ---------------------------------------------------------------------------
# _get_github_headers
# ---------------------------------------------------------------------------


class TestGetGitHubHeaders:
    """Tests for GitHub API header construction."""

    def test_with_rp_github_pat(self, clean_env):
        os.environ["RP_GITHUB_PAT"] = "test-pat-123"
        headers = _get_github_headers()
        assert headers["Authorization"] == "Bearer test-pat-123"
        assert headers["Accept"] == "application/vnd.github+json"
        assert headers["X-GitHub-Api-Version"] == "2022-11-28"

    def test_fallback_to_github_pat(self, clean_env):
        os.environ["GITHUB_PAT"] = "fallback-pat-456"
        headers = _get_github_headers()
        assert headers["Authorization"] == "Bearer fallback-pat-456"

    def test_rp_takes_precedence(self, clean_env):
        os.environ["RP_GITHUB_PAT"] = "primary"
        os.environ["GITHUB_PAT"] = "fallback"
        headers = _get_github_headers()
        assert headers["Authorization"] == "Bearer primary"

    def test_no_pat_no_auth_header(self, clean_env):
        # Remove any existing PAT
        os.environ.pop("GITHUB_PAT", None)
        headers = _get_github_headers()
        assert "Authorization" not in headers
        assert "Accept" in headers


# ---------------------------------------------------------------------------
# _check_rate_limit
# ---------------------------------------------------------------------------


class TestCheckRateLimit:
    """Tests for GitHub rate limit handling."""

    @patch("services.orchestrator.github_search.time.sleep")
    def test_low_remaining_sleeps(self, mock_sleep):
        future_reset = int(time.time()) + 10
        _check_rate_limit({
            "x-ratelimit-remaining": "1",
            "x-ratelimit-reset": str(future_reset),
        })
        mock_sleep.assert_called_once()
        sleep_time = mock_sleep.call_args[0][0]
        assert sleep_time > 0

    @patch("services.orchestrator.github_search.time.sleep")
    def test_high_remaining_no_sleep(self, mock_sleep):
        _check_rate_limit({
            "x-ratelimit-remaining": "30",
            "x-ratelimit-reset": str(int(time.time()) + 100),
        })
        mock_sleep.assert_not_called()

    @patch("services.orchestrator.github_search.time.sleep")
    def test_missing_headers_no_sleep(self, mock_sleep):
        _check_rate_limit({})
        mock_sleep.assert_not_called()

    @patch("services.orchestrator.github_search.time.sleep")
    def test_past_reset_no_sleep(self, mock_sleep):
        past_reset = int(time.time()) - 100
        _check_rate_limit({
            "x-ratelimit-remaining": "0",
            "x-ratelimit-reset": str(past_reset),
        })
        mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# build_dynamic_prompt
# ---------------------------------------------------------------------------


class TestBuildDynamicPrompt:
    """Tests for analysis prompt construction."""

    def test_basic_prompt(self):
        paper = {"title": "Test Paper", "abstract": "Abstract text", "stage": "extracted"}
        repo = {"full_name": "user/repo", "description": "A repo", "stars": 10, "language": "Python"}
        prompt = build_dynamic_prompt(paper, repo)

        assert "Test Paper" in prompt
        assert "Abstract text" in prompt
        assert "user/repo" in prompt
        assert "Python" in prompt
        assert "relevance_score" in prompt

    def test_with_formulas(self):
        paper = {
            "title": "Kelly Paper",
            "abstract": "Abstract",
            "stage": "extracted",
            "formulas": [
                {"latex": "f = p/a", "description": "Kelly formula"},
                {"latex": "G(f) = r + f*m", "description": None},
            ],
        }
        repo = {"full_name": "u/r", "stars": 5, "language": "Rust"}
        prompt = build_dynamic_prompt(paper, repo)

        assert "f = p/a" in prompt
        assert "Kelly formula" in prompt
        assert "Key Formulas" in prompt

    def test_no_formulas(self):
        paper = {"title": "Paper", "stage": "discovered"}
        repo = {"full_name": "u/r", "stars": 1}
        prompt = build_dynamic_prompt(paper, repo)

        assert "Key Formulas" not in prompt

    def test_long_abstract_truncated(self):
        paper = {
            "title": "Paper",
            "abstract": "A" * 2000,
            "stage": "extracted",
        }
        repo = {"full_name": "u/r", "stars": 1}
        prompt = build_dynamic_prompt(paper, repo)

        # Abstract truncated to 800 chars
        assert "A" * 800 in prompt
        assert "A" * 801 not in prompt

    def test_max_15_formulas(self):
        formulas = [{"latex": f"x_{i}", "description": f"formula {i}"} for i in range(20)]
        paper = {"title": "P", "stage": "e", "formulas": formulas}
        repo = {"full_name": "u/r", "stars": 1}
        prompt = build_dynamic_prompt(paper, repo)

        assert "x_14" in prompt
        assert "x_15" not in prompt


# ---------------------------------------------------------------------------
# _parse_json_response
# ---------------------------------------------------------------------------


class TestParseJsonResponse:
    """Tests for JSON response parsing."""

    def test_plain_json(self):
        result = _parse_json_response('{"score": 85}')
        assert result == {"score": 85}

    def test_markdown_fenced_json(self):
        text = '```json\n{"score": 85}\n```'
        result = _parse_json_response(text)
        assert result == {"score": 85}

    def test_markdown_fenced_no_lang(self):
        text = '```\n{"score": 85}\n```'
        result = _parse_json_response(text)
        assert result == {"score": 85}

    def test_whitespace_around(self):
        result = _parse_json_response('  \n  {"score": 85}  \n  ')
        assert result == {"score": 85}

    def test_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_json_response("not json at all")

    def test_complex_nested_json(self):
        data = {
            "relevance_score": 90,
            "formula_matches": [{"formula": "x^2", "file": "main.py"}],
            "recommendation": "USE",
        }
        result = _parse_json_response(json.dumps(data))
        assert result == data


# ---------------------------------------------------------------------------
# _read_repo_files
# ---------------------------------------------------------------------------


class TestReadRepoFiles:
    """Tests for repository file reading."""

    def test_reads_python_files(self, tmp_path):
        (tmp_path / "main.py").write_text("print('hello')")
        (tmp_path / "lib.py").write_text("def foo(): pass")
        result = _read_repo_files(tmp_path)

        assert "main.py" in result
        assert "lib.py" in result
        assert "print('hello')" in result

    def test_reads_rust_files(self, tmp_path):
        (tmp_path / "main.rs").write_text("fn main() {}")
        result = _read_repo_files(tmp_path)

        assert "main.rs" in result
        assert "fn main()" in result

    def test_reads_c_cpp_files(self, tmp_path):
        (tmp_path / "main.c").write_text("int main() { return 0; }")
        (tmp_path / "lib.hpp").write_text("class Foo {};")
        result = _read_repo_files(tmp_path)

        assert "main.c" in result
        assert "lib.hpp" in result

    def test_skips_non_code_files(self, tmp_path):
        (tmp_path / "readme.md").write_text("# README")
        (tmp_path / "data.json").write_text("{}")
        (tmp_path / "main.py").write_text("code")
        result = _read_repo_files(tmp_path)

        assert "readme.md" not in result
        assert "data.json" not in result
        assert "main.py" in result

    def test_skips_skip_dirs(self, tmp_path):
        venv = tmp_path / "venv"
        venv.mkdir()
        (venv / "module.py").write_text("skip me")
        (tmp_path / "main.py").write_text("include me")
        result = _read_repo_files(tmp_path)

        assert "skip me" not in result
        assert "include me" in result

    def test_max_chars_limit(self, tmp_path):
        (tmp_path / "big.py").write_text("x" * 1000)
        result = _read_repo_files(tmp_path, max_chars=500)

        # Content should be limited
        assert len(result) <= 600  # Some overhead from headers

    def test_empty_repo(self, tmp_path):
        result = _read_repo_files(tmp_path)
        assert result == ""


# ---------------------------------------------------------------------------
# _generate_queries
# ---------------------------------------------------------------------------


class TestGenerateQueries:
    """Tests for search query generation."""

    def test_basic_query_generation(self):
        paper = {"title": "Kelly Criterion Portfolio Optimization"}
        queries = _generate_queries(paper)

        assert len(queries) >= 1
        # First query should be quoted keywords
        assert '"' in queries[0]

    def test_fallback_query_with_in_readme(self):
        paper = {"title": "Kelly Criterion Portfolio Optimization"}
        queries = _generate_queries(paper)

        assert len(queries) >= 2
        assert "in:readme" in queries[1]

    def test_empty_title_fallback(self):
        paper = {"title": ""}
        queries = _generate_queries(paper)
        assert len(queries) >= 1

    def test_short_title(self):
        paper = {"title": "Kelly Criterion"}
        queries = _generate_queries(paper)
        assert len(queries) >= 1


# ---------------------------------------------------------------------------
# clone_repo / cleanup_clone
# ---------------------------------------------------------------------------


class TestCloneAndCleanup:
    """Tests for git clone and cleanup."""

    @patch("services.orchestrator.github_search.subprocess.run")
    def test_clone_calls_git(self, mock_run, clean_env):
        mock_run.return_value = MagicMock(returncode=0)
        result = clone_repo("https://github.com/user/repo.git", timeout=30)

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert "git" in call_args[0][0]
        assert "--depth" in call_args[0][0]
        assert "1" in call_args[0][0]
        assert isinstance(result, Path)

        # Cleanup the temp dir
        cleanup_clone(result)

    @patch("services.orchestrator.github_search.subprocess.run")
    def test_clone_uses_env_timeout(self, mock_run, clean_env):
        os.environ["RP_GITHUB_CLONE_TIMEOUT"] = "120"
        mock_run.return_value = MagicMock(returncode=0)
        clone_repo("https://github.com/user/repo.git")

        assert mock_run.call_args[1]["timeout"] == 120

    def test_cleanup_only_removes_temp_dirs(self):
        # Create a dir outside tempdir to verify cleanup_clone won't remove it
        import shutil
        non_temp = Path("/media/sam/1TB/research-pipeline/.pytest_cleanup_test")
        non_temp.mkdir(exist_ok=True)
        fake_repo = non_temp / "repo"
        fake_repo.mkdir(exist_ok=True)
        try:
            cleanup_clone(fake_repo)
            # Parent should still exist since it's not in tempdir
            assert non_temp.exists()
        finally:
            shutil.rmtree(non_temp, ignore_errors=True)

    def test_cleanup_removes_temp_dir(self):
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="research-github-"))
        repo_path = tmp / "repo"
        repo_path.mkdir()
        cleanup_clone(repo_path)
        assert not tmp.exists()


# ---------------------------------------------------------------------------
# Constants sanity
# ---------------------------------------------------------------------------


class TestConstants:
    """Verify module constants are sane."""

    def test_extensions_set(self):
        assert "*.py" in EXTENSIONS
        assert "*.rs" in EXTENSIONS
        assert "*.cpp" in EXTENSIONS

    def test_skip_dirs_set(self):
        assert "venv" in SKIP_DIRS
        assert ".git" in SKIP_DIRS
        assert "node_modules" in SKIP_DIRS
        assert "target" in SKIP_DIRS

    def test_stop_words_set(self):
        assert "the" in STOP_WORDS
        assert "of" in STOP_WORDS
        assert "optimal" in STOP_WORDS
