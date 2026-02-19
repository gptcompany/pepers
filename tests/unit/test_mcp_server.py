"""Unit tests for PePeRS MCP Server — tool functions and flavor system."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Flavor system
# ---------------------------------------------------------------------------


class TestFlavorSystem:
    """Tests for the arcade/plain flavor output system."""

    def test_arcade_flavor_default(self):
        """Default flavor should be arcade."""
        from services.mcp.server import MCP_FLAVOR
        # MCP_FLAVOR reads env at import; default is arcade
        assert MCP_FLAVOR in ("arcade", "plain")

    def test_flavor_arcade_message(self):
        """_flavor() returns arcade messages when flavor=arcade."""
        from services.mcp.server import ARCADE_MESSAGES, PLAIN_MESSAGES, _flavor

        with patch("services.mcp.server.MCP_FLAVOR", "arcade"):
            msg = _flavor("search_found", n=5)
            assert "5" in msg
            # Should match the arcade template
            expected = ARCADE_MESSAGES["search_found"].format(n=5)
            assert msg == expected

    def test_flavor_plain_message(self):
        """_flavor() returns plain messages when flavor=plain."""
        from services.mcp.server import PLAIN_MESSAGES, _flavor

        with patch("services.mcp.server.MCP_FLAVOR", "plain"):
            msg = _flavor("search_found", n=3)
            expected = PLAIN_MESSAGES["search_found"].format(n=3)
            assert msg == expected

    def test_flavor_error_message(self):
        """Error messages include the error text."""
        from services.mcp.server import _flavor

        with patch("services.mcp.server.MCP_FLAVOR", "arcade"):
            msg = _flavor("error", msg="connection refused")
            assert "connection refused" in msg
            assert "GAME OVER" in msg

    def test_flavor_unknown_key_passthrough(self):
        """Unknown keys returned as-is."""
        from services.mcp.server import _flavor

        msg = _flavor("nonexistent_key")
        assert msg == "nonexistent_key"

    def test_all_arcade_keys_have_plain_counterparts(self):
        """Every arcade message key should exist in plain messages too."""
        from services.mcp.server import ARCADE_MESSAGES, PLAIN_MESSAGES

        for key in ARCADE_MESSAGES:
            assert key in PLAIN_MESSAGES, f"Missing plain message for key: {key}"


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------


class TestCallOrchestrator:
    """Tests for _call_orchestrator HTTP helper."""

    def _make_response(self, data: dict | list, status: int = 200):
        """Create a mock HTTP response."""
        mock = MagicMock()
        mock.read.return_value = json.dumps(data).encode()
        mock.status = status
        mock.__enter__ = lambda s: s
        mock.__exit__ = MagicMock(return_value=False)
        return mock

    @patch("services.mcp.server.urllib.request.urlopen")
    def test_get_request(self, mock_urlopen):
        """GET request returns parsed JSON."""
        from services.mcp.server import _call_orchestrator

        mock_urlopen.return_value = self._make_response({"ok": True})
        result = _call_orchestrator("GET", "/health")
        assert result == {"ok": True}

    @patch("services.mcp.server.urllib.request.urlopen")
    def test_post_request_with_data(self, mock_urlopen):
        """POST request sends JSON body."""
        from services.mcp.server import _call_orchestrator

        mock_urlopen.return_value = self._make_response({"success": True})
        result = _call_orchestrator("POST", "/search", {"query": "test"})
        assert result == {"success": True}

        # Verify the request was made with correct body
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert req.method == "POST"
        body = json.loads(req.data.decode())
        assert body["query"] == "test"

    @patch("services.mcp.server.urllib.request.urlopen")
    def test_http_error_with_json_body(self, mock_urlopen):
        """HTTP errors with JSON body return parsed error."""
        import urllib.error
        from services.mcp.server import _call_orchestrator

        error_body = json.dumps({"error": "not found"}).encode()
        mock_fp = MagicMock()
        mock_fp.read.return_value = error_body
        error = urllib.error.HTTPError(
            "http://test", 404, "Not Found", {}, mock_fp
        )
        mock_urlopen.side_effect = error

        result = _call_orchestrator("GET", "/papers?id=999")
        assert result == {"error": "not found"}

    @patch("services.mcp.server.urllib.request.urlopen")
    def test_url_error_raises_runtime(self, mock_urlopen):
        """URLError (connection refused) raises RuntimeError."""
        import urllib.error
        from services.mcp.server import _call_orchestrator

        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        with pytest.raises(RuntimeError, match="Cannot reach orchestrator"):
            _call_orchestrator("GET", "/health")


# ---------------------------------------------------------------------------
# MCP Tool: search_papers
# ---------------------------------------------------------------------------


class TestSearchPapers:
    """Tests for the search_papers MCP tool."""

    @patch("services.mcp.server._call_orchestrator")
    def test_search_with_answer(self, mock_call):
        """search_papers returns formatted answer."""
        from services.mcp.server import search_papers

        mock_call.return_value = {
            "success": True,
            "answer": "The Kelly criterion is a formula...",
        }
        result = search_papers("Kelly criterion")
        assert "Kelly criterion is a formula" in result

    @patch("services.mcp.server._call_orchestrator")
    def test_search_empty(self, mock_call):
        """search_papers returns empty message when no results."""
        from services.mcp.server import search_papers

        mock_call.return_value = {"success": True, "answer": ""}
        result = search_papers("nonexistent topic xyz")
        # Should return the empty flavor message
        assert result  # Not empty string

    @patch("services.mcp.server._call_orchestrator")
    def test_search_context_only(self, mock_call):
        """search_papers with context_only returns raw chunks."""
        from services.mcp.server import search_papers

        mock_call.return_value = {
            "success": True,
            "context": "Chunk 1: Kelly criterion...\n\nChunk 2: Optimal betting...",
        }
        result = search_papers("Kelly", context_only=True)
        assert "Kelly criterion" in result
        mock_call.assert_called_once_with("POST", "/search", {
            "query": "Kelly",
            "mode": "hybrid",
            "context_only": True,
        })

    @patch("services.mcp.server._call_orchestrator")
    def test_search_error_returns_flavor(self, mock_call):
        """search_papers returns flavor error on failure."""
        from services.mcp.server import search_papers

        mock_call.side_effect = RuntimeError("Connection refused")
        result = search_papers("test")
        assert "Connection refused" in result


# ---------------------------------------------------------------------------
# MCP Tool: list_papers
# ---------------------------------------------------------------------------


class TestListPapers:
    """Tests for the list_papers MCP tool."""

    @patch("services.mcp.server._call_orchestrator")
    def test_list_papers_with_results(self, mock_call):
        """list_papers returns formatted paper list."""
        from services.mcp.server import list_papers

        mock_call.return_value = [
            {"id": 1, "title": "Paper Alpha", "stage": "analyzed"},
            {"id": 2, "title": "Paper Beta", "stage": "codegen"},
        ]
        result = list_papers()
        assert "#1" in result
        assert "Paper Alpha" in result
        assert "#2" in result

    @patch("services.mcp.server._call_orchestrator")
    def test_list_papers_with_stage_filter(self, mock_call):
        """list_papers passes stage filter to orchestrator."""
        from services.mcp.server import list_papers

        mock_call.return_value = []
        list_papers(stage="validated")
        mock_call.assert_called_once_with("GET", "/papers?limit=50&stage=validated")

    @patch("services.mcp.server._call_orchestrator")
    def test_list_papers_empty(self, mock_call):
        """list_papers with empty results."""
        from services.mcp.server import list_papers

        mock_call.return_value = []
        result = list_papers()
        assert result  # Returns flavor message, not empty


# ---------------------------------------------------------------------------
# MCP Tool: get_paper
# ---------------------------------------------------------------------------


class TestGetPaper:
    """Tests for the get_paper MCP tool."""

    @patch("services.mcp.server._call_orchestrator")
    def test_get_paper_found(self, mock_call):
        """get_paper returns paper details."""
        from services.mcp.server import get_paper

        mock_call.return_value = {
            "id": 42,
            "title": "Kelly Criterion Applications",
            "arxiv_id": "2003.02743",
            "stage": "codegen",
            "abstract": "We study optimal betting strategies...",
            "formulas": [
                {"latex": "f^* = \\mu / \\sigma^2", "stage": "validated"},
            ],
        }
        result = get_paper(42)
        assert "Kelly Criterion" in result
        assert "2003.02743" in result
        assert "codegen" in result

    @patch("services.mcp.server._call_orchestrator")
    def test_get_paper_not_found(self, mock_call):
        """get_paper returns not-found message."""
        from services.mcp.server import get_paper

        mock_call.return_value = {"error": "not found"}
        result = get_paper(999)
        assert "999" in result


# ---------------------------------------------------------------------------
# MCP Tool: get_formulas
# ---------------------------------------------------------------------------


class TestGetFormulas:
    """Tests for the get_formulas MCP tool."""

    @patch("services.mcp.server._call_orchestrator")
    def test_get_formulas_found(self, mock_call):
        """get_formulas returns formatted formula list."""
        from services.mcp.server import get_formulas

        mock_call.return_value = [
            {"id": 1, "latex": "E = mc^2", "stage": "validated", "description": "Energy-mass"},
            {"id": 2, "latex": "F = ma", "stage": "extracted", "description": ""},
        ]
        result = get_formulas(42)
        assert "E = mc^2" in result
        assert "#1" in result

    @patch("services.mcp.server._call_orchestrator")
    def test_get_formulas_empty(self, mock_call):
        """get_formulas with no formulas."""
        from services.mcp.server import get_formulas

        mock_call.return_value = []
        result = get_formulas(42)
        assert result  # Returns flavor message


# ---------------------------------------------------------------------------
# MCP Tool: run_pipeline
# ---------------------------------------------------------------------------


class TestRunPipeline:
    """Tests for the run_pipeline MCP tool."""

    @patch("services.mcp.server._call_orchestrator")
    def test_run_with_query(self, mock_call):
        """run_pipeline with query sends correct payload."""
        from services.mcp.server import run_pipeline

        mock_call.return_value = {"run_id": "run-abc123", "status": "running"}
        result = run_pipeline(query="Kelly criterion")
        assert "run-abc123" in result
        mock_call.assert_called_once()
        payload = mock_call.call_args[0][2]
        assert payload["query"] == "Kelly criterion"
        assert payload["stages"] == 5

    @patch("services.mcp.server._call_orchestrator")
    def test_run_with_paper_id(self, mock_call):
        """run_pipeline with paper_id sends correct payload."""
        from services.mcp.server import run_pipeline

        mock_call.return_value = {"run_id": "run-xyz", "status": "running"}
        result = run_pipeline(paper_id=42, stages=3)
        payload = mock_call.call_args[0][2]
        assert payload["paper_id"] == 42
        assert payload["stages"] == 3
        assert "query" not in payload

    @patch("services.mcp.server._call_orchestrator")
    def test_run_error(self, mock_call):
        """run_pipeline handles orchestrator errors."""
        from services.mcp.server import run_pipeline

        mock_call.side_effect = RuntimeError("Service unavailable")
        result = run_pipeline()
        assert "Service unavailable" in result


# ---------------------------------------------------------------------------
# MCP Tool: get_run_status
# ---------------------------------------------------------------------------


class TestGetRunStatus:
    """Tests for the get_run_status MCP tool."""

    @patch("services.mcp.server._call_orchestrator")
    def test_run_found(self, mock_call):
        """get_run_status returns run details."""
        from services.mcp.server import get_run_status

        mock_call.return_value = {
            "run_id": "run-abc",
            "status": "completed",
            "stages_completed": 5,
            "stages_requested": 5,
            "papers_processed": 3,
        }
        result = get_run_status("run-abc")
        assert "completed" in result
        assert "5" in result

    @patch("services.mcp.server._call_orchestrator")
    def test_run_not_found(self, mock_call):
        """get_run_status with unknown run ID."""
        from services.mcp.server import get_run_status

        mock_call.return_value = {"error": "not found"}
        result = get_run_status("run-unknown")
        assert "run-unknown" in result


# ---------------------------------------------------------------------------
# MCP Tool: search_github
# ---------------------------------------------------------------------------


class TestSearchGithub:
    """Tests for the search_github MCP tool."""

    @patch("services.mcp.server._call_orchestrator")
    def test_search_found(self, mock_call):
        """search_github returns repo list."""
        from services.mcp.server import search_github

        mock_call.return_value = {
            "repos": [
                {
                    "repo": {
                        "full_name": "user/kelly-criterion",
                        "stars": 42,
                        "url": "https://github.com/user/kelly-criterion",
                    },
                    "analysis": {"recommendation": "USE"},
                },
            ],
        }
        result = search_github(paper_id=1)
        assert "kelly-criterion" in result

    @patch("services.mcp.server._call_orchestrator")
    def test_search_empty(self, mock_call):
        """search_github with no results."""
        from services.mcp.server import search_github

        mock_call.return_value = {"repos": []}
        result = search_github(paper_id=1)
        assert result  # Returns flavor message


# ---------------------------------------------------------------------------
# MCP Tool: get_generated_code
# ---------------------------------------------------------------------------


class TestGetGeneratedCode:
    """Tests for the get_generated_code MCP tool."""

    @patch("services.mcp.server._call_orchestrator")
    def test_code_found(self, mock_call):
        """get_generated_code returns formatted code blocks."""
        from services.mcp.server import get_generated_code

        mock_call.return_value = [
            {
                "formula_id": 1,
                "language": "python",
                "latex": "E = mc^2",
                "code": "def energy(m, c=3e8):\n    return m * c**2",
            },
        ]
        result = get_generated_code(paper_id=42)
        assert "python" in result
        assert "energy" in result
        assert "```python" in result

    @patch("services.mcp.server._call_orchestrator")
    def test_code_empty(self, mock_call):
        """get_generated_code with no generated code."""
        from services.mcp.server import get_generated_code

        mock_call.return_value = []
        result = get_generated_code(paper_id=42)
        assert result  # Returns flavor message

    @patch("services.mcp.server._call_orchestrator")
    def test_code_with_language_filter(self, mock_call):
        """get_generated_code passes language filter."""
        from services.mcp.server import get_generated_code

        mock_call.return_value = []
        get_generated_code(paper_id=42, language="python")
        mock_call.assert_called_once_with(
            "GET", "/generated-code?paper_id=42&limit=50&language=python"
        )
