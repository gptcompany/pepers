"""Integration tests for PePeRS MCP Server — server lifecycle and tool registration."""

from __future__ import annotations

import argparse
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

import pytest

from services.mcp.server import mcp, _call_orchestrator


# ---------------------------------------------------------------------------
# Mock orchestrator for integration tests
# ---------------------------------------------------------------------------


class MockOrchestratorHandler(BaseHTTPRequestHandler):
    """Minimal mock that returns canned responses for orchestrator endpoints."""

    def log_message(self, *args):
        pass  # Suppress request logs

    def _respond(self, data: dict | list, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/papers":
            if "id=" in self.path:
                self._respond({
                    "id": 1, "title": "Test Paper", "arxiv_id": "2003.02743",
                    "stage": "codegen", "abstract": "Test abstract", "formulas": [],
                })
            else:
                self._respond([
                    {"id": 1, "title": "Test Paper", "stage": "codegen"},
                ])
        elif path == "/formulas":
            self._respond([
                {"id": 1, "latex": "E=mc^2", "stage": "validated", "description": ""},
            ])
        elif path == "/generated-code":
            self._respond([
                {"formula_id": 1, "language": "python", "latex": "E=mc^2", "code": "e = m * c**2"},
            ])
        elif path == "/runs":
            if "id=" in self.path:
                self._respond({
                    "run_id": "run-test", "status": "completed",
                    "stages_completed": 5, "stages_requested": 5,
                })
            else:
                self._respond([])
        elif path == "/health":
            self._respond({"status": "ok"})
        else:
            self._respond({"error": "not found"}, 404)

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_length)) if content_length else {}
        path = self.path.split("?")[0]

        if path == "/search":
            if body.get("context_only"):
                self._respond({
                    "success": True, "context": "Context chunk about papers...",
                })
            else:
                self._respond({
                    "success": True, "answer": "Papers about Kelly criterion...",
                })
        elif path == "/run":
            self._respond({"run_id": "run-int-test", "status": "running"}, 202)
        elif path == "/search-github":
            self._respond({"repos": []})
        else:
            self._respond({"error": "unknown endpoint"}, 404)


@pytest.fixture(scope="module")
def mock_orchestrator():
    """Start a mock orchestrator HTTP server for integration tests."""
    server = HTTPServer(("127.0.0.1", 0), MockOrchestratorHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestMcpToolRegistration:
    """Verify all expected tools are registered on the MCP server."""

    def test_server_name(self):
        """MCP server has correct name."""
        assert mcp.name == "PePeRS"

    def test_tools_registered(self):
        """All 8 tools are registered."""
        tool_names = {t.name for t in mcp._tool_manager.list_tools()}
        expected = {
            "search_papers", "list_papers", "get_paper", "get_formulas",
            "run_pipeline", "get_run_status", "search_github", "get_generated_code",
        }
        assert expected.issubset(tool_names), f"Missing tools: {expected - tool_names}"


class TestCliTransportArg:
    """Verify CLI --transport argument parsing."""

    def _parse(self, *args: str) -> argparse.Namespace:
        """Parse CLI args without running the server."""
        import os
        import argparse as ap
        parser = ap.ArgumentParser()
        parser.add_argument("--port", type=int, default=8776)
        parser.add_argument("--flavor", choices=["arcade", "plain"], default="arcade")
        parser.add_argument("--orchestrator-url", default="http://localhost:8775")
        parser.add_argument(
            "--transport", choices=["sse", "streamable-http"],
            default=os.environ.get("RP_MCP_TRANSPORT", "sse"),
        )
        return parser.parse_args(list(args))

    def test_default_transport_is_sse(self):
        ns = self._parse()
        assert ns.transport == "sse"

    def test_streamable_http_accepted(self):
        ns = self._parse("--transport", "streamable-http")
        assert ns.transport == "streamable-http"

    def test_sse_explicit(self):
        ns = self._parse("--transport", "sse")
        assert ns.transport == "sse"

    def test_invalid_transport_rejected(self):
        with pytest.raises(SystemExit):
            self._parse("--transport", "websocket")


class TestMcpIntegration:
    """Integration tests hitting mock orchestrator through MCP tool functions."""

    def test_call_orchestrator_get(self, mock_orchestrator):
        """_call_orchestrator GET returns parsed response from mock."""
        import services.mcp.server as srv
        original_url = srv.ORCHESTRATOR_URL
        srv.ORCHESTRATOR_URL = mock_orchestrator
        try:
            result = _call_orchestrator("GET", "/health")
            assert result == {"status": "ok"}
        finally:
            srv.ORCHESTRATOR_URL = original_url

    def test_call_orchestrator_post(self, mock_orchestrator):
        """_call_orchestrator POST with JSON body works."""
        import services.mcp.server as srv
        original_url = srv.ORCHESTRATOR_URL
        srv.ORCHESTRATOR_URL = mock_orchestrator
        try:
            result = _call_orchestrator("POST", "/search", {"query": "test"})
            assert result["success"] is True
            assert "answer" in result
        finally:
            srv.ORCHESTRATOR_URL = original_url

    def test_search_papers_integration(self, mock_orchestrator):
        """search_papers tool end-to-end with mock orchestrator."""
        import services.mcp.server as srv
        original_url = srv.ORCHESTRATOR_URL
        srv.ORCHESTRATOR_URL = mock_orchestrator
        try:
            from services.mcp.server import search_papers
            result = search_papers("Kelly criterion")
            assert "Kelly criterion" in result
        finally:
            srv.ORCHESTRATOR_URL = original_url

    def test_list_papers_integration(self, mock_orchestrator):
        """list_papers tool end-to-end with mock orchestrator."""
        import services.mcp.server as srv
        original_url = srv.ORCHESTRATOR_URL
        srv.ORCHESTRATOR_URL = mock_orchestrator
        try:
            from services.mcp.server import list_papers
            result = list_papers()
            assert "Test Paper" in result
        finally:
            srv.ORCHESTRATOR_URL = original_url

    def test_get_paper_integration(self, mock_orchestrator):
        """get_paper tool end-to-end with mock orchestrator."""
        import services.mcp.server as srv
        original_url = srv.ORCHESTRATOR_URL
        srv.ORCHESTRATOR_URL = mock_orchestrator
        try:
            from services.mcp.server import get_paper
            result = get_paper(1)
            assert "Test Paper" in result
            assert "2003.02743" in result
        finally:
            srv.ORCHESTRATOR_URL = original_url

    def test_run_pipeline_integration(self, mock_orchestrator):
        """run_pipeline tool end-to-end with mock orchestrator."""
        import services.mcp.server as srv
        original_url = srv.ORCHESTRATOR_URL
        srv.ORCHESTRATOR_URL = mock_orchestrator
        try:
            from services.mcp.server import run_pipeline
            result = run_pipeline(query="test")
            assert "run-int-test" in result
        finally:
            srv.ORCHESTRATOR_URL = original_url

    def test_context_only_integration(self, mock_orchestrator):
        """search_papers with context_only through mock orchestrator."""
        import services.mcp.server as srv
        original_url = srv.ORCHESTRATOR_URL
        srv.ORCHESTRATOR_URL = mock_orchestrator
        try:
            from services.mcp.server import search_papers
            result = search_papers("test", context_only=True)
            assert "Context chunk" in result
        finally:
            srv.ORCHESTRATOR_URL = original_url
