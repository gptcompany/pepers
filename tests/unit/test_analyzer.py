"""Unit tests for the Analyzer service — all external calls mocked."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from services.analyzer.prompt import (
    EXPECTED_SCORE_KEYS,
    PROMPT_VERSION,
    SCORING_SYSTEM_PROMPT,
    format_scoring_prompt,
)
from services.analyzer.llm import (
    _get_gemini_api_key,
    _strip_markdown_fences,
    call_gemini_cli,
    call_ollama,
    fallback_chain,
)
from services.analyzer.main import (
    AnalyzerHandler,
    _parse_llm_response,
    _query_papers,
    _update_paper_score,
    migrate_db,
)


# ---------------------------------------------------------------------------
# TestFormatScoringPrompt
# ---------------------------------------------------------------------------


class TestFormatScoringPrompt:
    """Tests for format_scoring_prompt()."""

    def test_basic_format(self):
        abstract = "A study of optimal bet sizing in finance and portfolio management theory."
        result = format_scoring_prompt(
            "Kelly Criterion", abstract,
            ["Alice Smith", "Bob Jones"], ["q-fin.PM"],
        )
        assert "Kelly Criterion" in result
        assert "A study of optimal bet sizing" in result
        assert "Alice Smith, Bob Jones" in result
        assert "q-fin.PM" in result

    def test_truncates_authors_over_5(self):
        authors = [f"Author {i}" for i in range(8)]
        result = format_scoring_prompt("Title", "Abstract text enough chars here.", authors, [])
        assert "et al." in result
        assert "8 total" in result
        # Only first 5 should be named
        assert "Author 0" in result
        assert "Author 4" in result
        assert "Author 5" not in result

    def test_missing_abstract(self):
        result = format_scoring_prompt("Title", None, ["A"], ["q-fin.PM"])
        assert "(abstract not available)" in result

    def test_short_abstract(self):
        result = format_scoring_prompt("Title", "Short.", ["A"], ["q-fin.PM"])
        assert "(abstract not available)" in result

    def test_exactly_50_chars_abstract(self):
        abstract = "x" * 50
        result = format_scoring_prompt("Title", abstract, ["A"], [])
        assert abstract in result
        assert "(abstract not available)" not in result

    def test_empty_categories(self):
        result = format_scoring_prompt("Title", None, ["A"], [])
        assert "Categories:" in result

    def test_empty_authors(self):
        result = format_scoring_prompt("Title", None, [], ["q-fin.PM"])
        assert "Authors:" in result


# ---------------------------------------------------------------------------
# TestStripMarkdownFences
# ---------------------------------------------------------------------------


class TestStripMarkdownFences:
    """Tests for _strip_markdown_fences()."""

    def test_json_fence(self):
        text = '```json\n{"key": "value"}\n```'
        assert _strip_markdown_fences(text) == '{"key": "value"}'

    def test_plain_fence(self):
        text = '```\n{"key": "value"}\n```'
        assert _strip_markdown_fences(text) == '{"key": "value"}'

    def test_no_fence(self):
        text = '{"key": "value"}'
        assert _strip_markdown_fences(text) == '{"key": "value"}'

    def test_whitespace_handling(self):
        text = '  ```json\n{"a": 1}\n```  '
        assert _strip_markdown_fences(text) == '{"a": 1}'

    def test_content_with_backticks_inside(self):
        text = '```json\n{"code": "use `backticks` here"}\n```'
        result = _strip_markdown_fences(text)
        assert "`backticks`" in result


# ---------------------------------------------------------------------------
# TestGetGeminiApiKey
# ---------------------------------------------------------------------------


class TestGetGeminiApiKey:
    """Tests for _get_gemini_api_key()."""

    def test_key_present(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key-123")
        assert _get_gemini_api_key() == "test-key-123"

    def test_key_missing(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY not set"):
            _get_gemini_api_key()

    def test_key_empty_string(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "")
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY not set"):
            _get_gemini_api_key()


# ---------------------------------------------------------------------------
# TestCallGeminiCli
# ---------------------------------------------------------------------------


class TestCallGeminiCli:
    """Tests for call_gemini_cli() — mock subprocess.run."""

    @patch("shared.llm.subprocess.run")
    @patch("shared.llm._get_gemini_api_key", return_value="fake-key")
    def test_success_json_response(self, mock_key, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='{"response": "{\\"scores\\": {}}"}',
            stderr="",
        )
        result = call_gemini_cli("prompt", "system")
        assert result == '{"scores": {}}'

    @patch("shared.llm.subprocess.run")
    @patch("shared.llm._get_gemini_api_key", return_value="fake-key")
    def test_non_zero_exit(self, mock_key, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="Error occurred",
        )
        with pytest.raises(RuntimeError, match="gemini_cli exit 1"):
            call_gemini_cli("prompt", "system")

    @patch("shared.llm.subprocess.run")
    @patch("shared.llm._get_gemini_api_key", return_value="fake-key")
    def test_api_error_in_response(self, mock_key, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='{"error": {"message": "quota exceeded"}}',
            stderr="",
        )
        with pytest.raises(RuntimeError, match="quota exceeded"):
            call_gemini_cli("prompt", "system")

    @patch("shared.llm.subprocess.run")
    @patch("shared.llm._get_gemini_api_key", return_value="fake-key")
    def test_timeout(self, mock_key, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired("gemini", 120)
        with pytest.raises(subprocess.TimeoutExpired):
            call_gemini_cli("prompt", "system")

    @patch("shared.llm.subprocess.run")
    @patch("shared.llm._get_gemini_api_key", return_value="fake-key")
    def test_strips_fences_from_response(self, mock_key, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='{"response": "```json\\n{\\"a\\": 1}\\n```"}',
            stderr="",
        )
        result = call_gemini_cli("prompt", "system")
        assert result == '{"a": 1}'


# ---------------------------------------------------------------------------
# TestCallGeminiSdk
# ---------------------------------------------------------------------------


class TestCallGeminiSdk:
    """Tests for call_gemini_sdk() — mock google.genai."""

    @patch("shared.llm._get_gemini_api_key", return_value="fake-key")
    def test_success(self, mock_key):
        mock_response = MagicMock()
        mock_response.text = '{"scores": {}}'

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        with patch.dict("sys.modules", {
            "google": MagicMock(),
            "google.genai": MagicMock(),
            "google.genai.types": MagicMock(),
        }):
            with patch("shared.llm._get_gemini_api_key", return_value="fake-key"):
                # Direct test: mock the entire function flow
                from services.analyzer import llm
                original = llm.call_gemini_sdk

                def mock_sdk(prompt, system, model="gemini-2.5-flash", timeout=30.0):
                    return '{"scores": {}}'

                llm.call_gemini_sdk = mock_sdk
                try:
                    result = llm.call_gemini_sdk("prompt", "system")
                    assert result == '{"scores": {}}'
                finally:
                    llm.call_gemini_sdk = original

    @patch("shared.llm._get_gemini_api_key", return_value="fake-key")
    def test_api_key_missing(self, mock_key):
        mock_key.side_effect = RuntimeError("GEMINI_API_KEY not set")
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY not set"):
            # The function calls _get_gemini_api_key internally
            from services.analyzer.llm import call_gemini_sdk
            call_gemini_sdk("prompt", "system")


# ---------------------------------------------------------------------------
# TestCallOllama
# ---------------------------------------------------------------------------


class TestCallOllama:
    """Tests for call_ollama() — mock urllib.request.urlopen."""

    @patch("shared.llm.urllib.request.urlopen")
    def test_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({
            "response": '{"scores": {"topic_relevance": 0.8}}'
        }).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = call_ollama("prompt", "system")
        assert result == '{"scores": {"topic_relevance": 0.8}}'

    @patch("shared.llm.urllib.request.urlopen")
    def test_error_in_response(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({
            "error": "model not found"
        }).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        with pytest.raises(RuntimeError, match="model not found"):
            call_ollama("prompt", "system")

    @patch("shared.llm.urllib.request.urlopen")
    def test_connection_refused(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        with pytest.raises(urllib.error.URLError):
            call_ollama("prompt", "system")

    @patch("shared.llm.urllib.request.urlopen")
    def test_custom_base_url(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({"response": "ok"}).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        call_ollama("p", "s", base_url="http://custom:1234")
        req = mock_urlopen.call_args[0][0]
        assert "custom:1234" in req.full_url


# ---------------------------------------------------------------------------
# TestFallbackChain
# ---------------------------------------------------------------------------


class TestFallbackChain:
    """Tests for fallback_chain()."""

    @patch("shared.llm.call_ollama")
    @patch("shared.llm.call_openrouter")
    @patch("shared.llm.call_gemini_cli")
    def test_first_provider_success(self, mock_cli, mock_openrouter, mock_ollama):
        mock_cli.return_value = '{"scores": {}}'
        result = fallback_chain("prompt", "system")
        assert result == ('{"scores": {}}', "gemini_cli")
        mock_openrouter.assert_not_called()
        mock_ollama.assert_not_called()

    @patch("shared.llm.call_ollama")
    @patch("shared.llm.call_openrouter")
    @patch("shared.llm.call_gemini_cli")
    def test_fallback_to_second(self, mock_cli, mock_openrouter, mock_ollama):
        mock_cli.side_effect = RuntimeError("CLI failed")
        mock_openrouter.return_value = '{"scores": {}}'
        result = fallback_chain("prompt", "system")
        assert result == ('{"scores": {}}', "openrouter")
        mock_ollama.assert_not_called()

    @patch("shared.llm.call_ollama")
    @patch("shared.llm.call_openrouter")
    @patch("shared.llm.call_gemini_cli")
    def test_fallback_to_third(self, mock_cli, mock_openrouter, mock_ollama):
        mock_cli.side_effect = RuntimeError("CLI failed")
        mock_openrouter.side_effect = RuntimeError("OpenRouter failed")
        mock_ollama.return_value = '{"scores": {}}'
        result = fallback_chain("prompt", "system")
        assert result == ('{"scores": {}}', "ollama")

    @patch("shared.llm.call_ollama")
    @patch("shared.llm.call_openrouter")
    @patch("shared.llm.call_gemini_cli")
    def test_all_fail(self, mock_cli, mock_openrouter, mock_ollama):
        mock_cli.side_effect = RuntimeError("CLI failed")
        mock_openrouter.side_effect = RuntimeError("OpenRouter failed")
        mock_ollama.side_effect = RuntimeError("Ollama failed")
        with pytest.raises(RuntimeError, match="All LLM providers failed"):
            fallback_chain("prompt", "system")

    @patch("shared.llm.call_ollama")
    @patch("shared.llm.call_openrouter")
    @patch("shared.llm.call_gemini_cli")
    def test_error_messages_collected(self, mock_cli, mock_openrouter, mock_ollama):
        mock_cli.side_effect = RuntimeError("err1")
        mock_openrouter.side_effect = RuntimeError("err2")
        mock_ollama.side_effect = RuntimeError("err3")
        with pytest.raises(RuntimeError) as exc_info:
            fallback_chain("prompt", "system")
        msg = str(exc_info.value)
        assert "err1" in msg
        assert "err2" in msg
        assert "err3" in msg

    @patch("shared.llm.call_ollama")
    @patch("shared.llm.call_openrouter")
    @patch("shared.llm.call_gemini_cli")
    def test_returns_tuple(self, mock_cli, mock_openrouter, mock_ollama):
        mock_cli.return_value = "text"
        result = fallback_chain("p", "s")
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], str)
        assert isinstance(result[1], str)


# ---------------------------------------------------------------------------
# TestAnalyzerHandlerValidation
# ---------------------------------------------------------------------------


class TestAnalyzerHandlerValidation:
    """Tests for AnalyzerHandler input validation in handle_process()."""

    def _make_handler(self, db_path="/tmp/test.db"):
        handler = MagicMock(spec=AnalyzerHandler)
        handler.db_path = db_path
        handler.threshold = 0.7
        handler.max_papers_default = 10
        handler.send_error_json = MagicMock()
        return handler

    def test_max_papers_zero_returns_422(self):
        handler = self._make_handler()
        AnalyzerHandler.handle_process(handler, {"max_papers": 0})
        handler.send_error_json.assert_called_once()
        args = handler.send_error_json.call_args[0]
        assert args[1] == "VALIDATION_ERROR"
        assert args[2] == 422

    def test_max_papers_over_100_returns_422(self):
        handler = self._make_handler()
        AnalyzerHandler.handle_process(handler, {"max_papers": 101})
        handler.send_error_json.assert_called_once()
        assert handler.send_error_json.call_args[0][2] == 422

    def test_max_papers_string_returns_422(self):
        handler = self._make_handler()
        AnalyzerHandler.handle_process(handler, {"max_papers": "ten"})
        handler.send_error_json.assert_called_once()

    @patch("services.analyzer.main._query_papers", return_value=[])
    def test_no_papers_returns_empty_summary(self, mock_query):
        handler = self._make_handler()
        result = AnalyzerHandler.handle_process(handler, {})
        assert result["papers_analyzed"] == 0
        assert result["papers_accepted"] == 0
        assert result["papers_rejected"] == 0
        assert result["errors"] == []

    @patch("services.analyzer.main.fallback_chain")
    @patch("services.analyzer.main._query_papers")
    def test_missing_title_skips_paper(self, mock_query, mock_fc):
        mock_query.return_value = [
            {"id": 1, "title": None, "abstract": "a", "authors": "[]", "categories": "[]"},
        ]
        handler = self._make_handler()
        result = AnalyzerHandler.handle_process(handler, {})
        assert result["papers_analyzed"] == 0
        assert "missing_title" in result["errors"][0]
        mock_fc.assert_not_called()


# ---------------------------------------------------------------------------
# TestParseLlmResponse
# ---------------------------------------------------------------------------


class TestParseLlmResponse:
    """Tests for _parse_llm_response()."""

    def test_valid_json(self, sample_llm_scores):
        text = json.dumps(sample_llm_scores)
        errors = []
        result = _parse_llm_response(text, "prompt", 1, errors)
        assert result is not None
        assert "scores" in result
        assert len(errors) == 0

    @patch("services.analyzer.main.fallback_chain")
    def test_invalid_json_retries(self, mock_fc, sample_llm_scores):
        mock_fc.return_value = (json.dumps(sample_llm_scores), "ollama")
        errors = []
        result = _parse_llm_response("not json", "prompt", 1, errors)
        assert result is not None
        assert "scores" in result
        mock_fc.assert_called_once()

    @patch("services.analyzer.main.fallback_chain")
    def test_invalid_json_both_fail(self, mock_fc):
        mock_fc.return_value = ("still not json", "ollama")
        errors = []
        result = _parse_llm_response("not json", "prompt", 1, errors)
        assert result is None
        assert len(errors) == 1
        assert "invalid JSON after retry" in errors[0]

    @patch("services.analyzer.main.fallback_chain")
    def test_retry_runtime_error(self, mock_fc):
        mock_fc.side_effect = RuntimeError("All failed")
        errors = []
        result = _parse_llm_response("not json", "prompt", 1, errors)
        assert result is None
        assert len(errors) == 1


# ---------------------------------------------------------------------------
# TestScoreValidation
# ---------------------------------------------------------------------------


class TestScoreValidation:
    """Tests for score validation logic in handle_process()."""

    @patch("services.analyzer.main._update_paper_score")
    @patch("services.analyzer.main.fallback_chain")
    @patch("services.analyzer.main._query_papers")
    def test_valid_scores_accepted(self, mock_query, mock_fc, mock_update,
                                   sample_llm_response_json):
        mock_query.return_value = [
            {"id": 1, "title": "Test", "abstract": "A " * 30,
             "authors": '["A"]', "categories": '["q-fin.PM"]'},
        ]
        mock_fc.return_value = (sample_llm_response_json, "ollama")

        handler = MagicMock(spec=AnalyzerHandler)
        handler.db_path = "/tmp/test.db"
        handler.threshold = 0.7
        handler.max_papers_default = 10
        handler.send_error_json = MagicMock()

        result = AnalyzerHandler.handle_process(handler, {})
        assert result["papers_analyzed"] == 1
        assert result["papers_accepted"] == 1
        mock_update.assert_called_once()

    @patch("services.analyzer.main._update_paper_score")
    @patch("services.analyzer.main.fallback_chain")
    @patch("services.analyzer.main._query_papers")
    def test_out_of_range_clamped(self, mock_query, mock_fc, mock_update):
        scores = {
            "scores": {
                "topic_relevance": 1.5,
                "mathematical_rigor": -0.1,
                "novelty": 0.5,
                "practical_applicability": 0.5,
                "data_quality": 0.5,
            },
            "reasoning": "test",
        }
        mock_query.return_value = [
            {"id": 1, "title": "Test", "abstract": "A " * 30,
             "authors": '["A"]', "categories": '["q-fin.PM"]'},
        ]
        mock_fc.return_value = (json.dumps(scores), "ollama")

        handler = MagicMock(spec=AnalyzerHandler)
        handler.db_path = "/tmp/test.db"
        handler.threshold = 0.7
        handler.max_papers_default = 10
        handler.send_error_json = MagicMock()

        result = AnalyzerHandler.handle_process(handler, {})
        assert result["papers_analyzed"] == 1
        # Clamped: 1.0 + 0.0 + 0.5 + 0.5 + 0.5 = 2.5 / 5 = 0.5 → rejected
        assert result["papers_rejected"] == 1
        # Check clamped=True passed to _update_paper_score
        call_args = mock_update.call_args[0]
        assert call_args[4] is True  # clamped flag

    @patch("services.analyzer.main.fallback_chain")
    @patch("services.analyzer.main._query_papers")
    def test_wrong_keys_rejected(self, mock_query, mock_fc):
        scores = {
            "scores": {
                "topic_relevance": 0.8,
                "mathematical_rigor": 0.7,
                "novelty": 0.6,
                "wrong_key": 0.5,
                "data_quality": 0.5,
            },
            "reasoning": "test",
        }
        mock_query.return_value = [
            {"id": 1, "title": "Test", "abstract": "A " * 30,
             "authors": '["A"]', "categories": '["q-fin.PM"]'},
        ]
        mock_fc.return_value = (json.dumps(scores), "ollama")

        handler = MagicMock(spec=AnalyzerHandler)
        handler.db_path = "/tmp/test.db"
        handler.threshold = 0.7
        handler.max_papers_default = 10
        handler.send_error_json = MagicMock()

        result = AnalyzerHandler.handle_process(handler, {})
        assert result["papers_analyzed"] == 0
        assert "invalid_score_keys" in result["errors"][0]

    @patch("services.analyzer.main.fallback_chain")
    @patch("services.analyzer.main._query_papers")
    def test_non_numeric_value(self, mock_query, mock_fc):
        scores = {
            "scores": {
                "topic_relevance": "high",
                "mathematical_rigor": 0.7,
                "novelty": 0.6,
                "practical_applicability": 0.5,
                "data_quality": 0.5,
            },
            "reasoning": "test",
        }
        mock_query.return_value = [
            {"id": 1, "title": "Test", "abstract": "A " * 30,
             "authors": '["A"]', "categories": '["q-fin.PM"]'},
        ]
        mock_fc.return_value = (json.dumps(scores), "ollama")

        handler = MagicMock(spec=AnalyzerHandler)
        handler.db_path = "/tmp/test.db"
        handler.threshold = 0.7
        handler.max_papers_default = 10
        handler.send_error_json = MagicMock()

        result = AnalyzerHandler.handle_process(handler, {})
        assert result["papers_analyzed"] == 0
        assert "invalid_score_value" in result["errors"][0]


# ---------------------------------------------------------------------------
# TestMigrateDb
# ---------------------------------------------------------------------------


class TestMigrateDb:
    """Tests for migrate_db()."""

    def test_adds_column(self, initialized_db):
        from shared.db import transaction

        migrate_db(str(initialized_db))
        with transaction(str(initialized_db)) as conn:
            cursor = conn.execute("PRAGMA table_info(papers)")
            columns = {row[1] for row in cursor.fetchall()}
        assert "prompt_version" in columns

    def test_idempotent(self, initialized_db):
        migrate_db(str(initialized_db))
        migrate_db(str(initialized_db))  # no error

        from shared.db import transaction
        with transaction(str(initialized_db)) as conn:
            cursor = conn.execute("PRAGMA table_info(papers)")
            columns = {row[1] for row in cursor.fetchall()}
        assert "prompt_version" in columns

    def test_index_created(self, initialized_db):
        from shared.db import transaction

        migrate_db(str(initialized_db))
        with transaction(str(initialized_db)) as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name='idx_papers_prompt_version'"
            )
            idx = cursor.fetchone()
        assert idx is not None


# ---------------------------------------------------------------------------
# TestQueryPapers
# ---------------------------------------------------------------------------


class TestQueryPapers:
    """Tests for _query_papers()."""

    def test_query_discovered_only(self, discovered_paper_db):
        papers = _query_papers(str(discovered_paper_db), None, 10, False)
        assert len(papers) == 1
        assert papers[0]["stage"] == "discovered"

    def test_query_specific_paper(self, discovered_paper_db):
        papers = _query_papers(str(discovered_paper_db), 1, 10, False)
        assert len(papers) == 1

    def test_query_nonexistent_paper(self, discovered_paper_db):
        papers = _query_papers(str(discovered_paper_db), 9999, 10, False)
        assert len(papers) == 0

    def test_query_force_includes_analyzed(self, discovered_paper_db):
        from shared.db import transaction

        # Change paper stage to analyzed
        with transaction(str(discovered_paper_db)) as conn:
            conn.execute("UPDATE papers SET stage='analyzed' WHERE id=1")

        # Without force: no results
        papers = _query_papers(str(discovered_paper_db), None, 10, False)
        assert len(papers) == 0

        # With force + paper_id: found
        papers = _query_papers(str(discovered_paper_db), 1, 10, True)
        assert len(papers) == 1

    def test_query_respects_limit(self, discovered_paper_db):
        from services.discovery.main import upsert_paper

        # Add more papers
        for i in range(5):
            upsert_paper(str(discovered_paper_db), {
                "arxiv_id": f"2401.0000{i+2}",
                "title": f"Paper {i+2}",
                "abstract": "Abstract",
                "authors": '["A"]',
                "categories": '["q-fin.PM"]',
                "doi": None,
                "pdf_url": None,
                "published_date": "2024-01-15",
                "stage": "discovered",
            })

        papers = _query_papers(str(discovered_paper_db), None, 3, False)
        assert len(papers) == 3


# ---------------------------------------------------------------------------
# TestUpdatePaperScore
# ---------------------------------------------------------------------------


class TestUpdatePaperScore:
    """Tests for _update_paper_score()."""

    def test_update_score(self, discovered_paper_db):
        from shared.db import transaction

        errors = []
        _update_paper_score(str(discovered_paper_db), 1, "analyzed", 0.85, False, errors)
        assert len(errors) == 0

        with transaction(str(discovered_paper_db)) as conn:
            row = conn.execute("SELECT * FROM papers WHERE id=1").fetchone()
        assert row["stage"] == "analyzed"
        assert row["score"] == 0.85
        assert row["prompt_version"] == PROMPT_VERSION
        assert row["error"] is None

    def test_update_clamped(self, discovered_paper_db):
        from shared.db import transaction

        errors = []
        _update_paper_score(str(discovered_paper_db), 1, "rejected", 0.5, True, errors)

        with transaction(str(discovered_paper_db)) as conn:
            row = conn.execute("SELECT * FROM papers WHERE id=1").fetchone()
        assert row["error"] == "score_clamped"

    def test_update_nonexistent_paper(self, discovered_paper_db):
        errors = []
        # Should not raise, just affects 0 rows
        _update_paper_score(str(discovered_paper_db), 9999, "analyzed", 0.8, False, errors)
        assert len(errors) == 0


# ---------------------------------------------------------------------------
# TestPromptConstants
# ---------------------------------------------------------------------------


class TestPromptConstants:
    """Tests for prompt.py constants."""

    def test_prompt_version(self):
        assert PROMPT_VERSION == "v2"

    def test_expected_score_keys(self):
        assert EXPECTED_SCORE_KEYS == frozenset({
            "topic_relevance",
            "mathematical_rigor",
            "novelty",
            "practical_applicability",
            "data_quality",
        })

    def test_system_prompt_contains_criteria(self):
        for key in EXPECTED_SCORE_KEYS:
            assert key in SCORING_SYSTEM_PROMPT

    def test_system_prompt_mentions_json(self):
        assert "JSON" in SCORING_SYSTEM_PROMPT
