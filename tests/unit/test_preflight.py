"""Unit tests for orchestrator preflight check on external dependencies."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import requests

from services.orchestrator.main import OrchestratorHandler
from services.orchestrator.pipeline import (
    EXTERNAL_DEPS,
    STAGE_EXTERNAL_DEPS,
    PipelineRunner,
)


class TestCheckExternalHealth:
    """Tests for PipelineRunner.check_external_health()."""

    def setup_method(self):
        self.runner = PipelineRunner.__new__(PipelineRunner)
        self.runner.db_path = ":memory:"

    @patch("services.orchestrator.pipeline.requests.get")
    def test_all_healthy(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        result = self.runner.check_external_health()

        assert result["all_healthy"] is True
        assert len(result["deps"]) == 3
        for dep_info in result["deps"].values():
            assert dep_info["healthy"] is True

    @patch("services.orchestrator.pipeline.requests.get")
    def test_one_unhealthy(self, mock_get):
        ok_resp = MagicMock(status_code=200)
        fail_resp = MagicMock(status_code=503)
        # CAS ok, RAG fail, Ollama ok
        mock_get.side_effect = [ok_resp, fail_resp, ok_resp]

        result = self.runner.check_external_health()

        assert result["all_healthy"] is False
        assert result["deps"]["cas"]["healthy"] is True
        assert result["deps"]["rag"]["healthy"] is False
        assert result["deps"]["ollama"]["healthy"] is True

    @patch("services.orchestrator.pipeline.requests.get")
    def test_connection_error_marks_unhealthy(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("Connection refused")

        result = self.runner.check_external_health()

        assert result["all_healthy"] is False
        for dep_info in result["deps"].values():
            assert dep_info["healthy"] is False

    @patch("services.orchestrator.pipeline.requests.get")
    def test_timeout_marks_unhealthy(self, mock_get):
        mock_get.side_effect = requests.Timeout("Read timed out")

        result = self.runner.check_external_health()

        assert result["all_healthy"] is False

    @patch("services.orchestrator.pipeline.requests.get")
    def test_cas_without_engines_marks_unhealthy(self, mock_get):
        cas_resp = MagicMock(status_code=200)
        cas_resp.json.return_value = {
            "status": "ok",
            "service": "cas-service",
            "engines_total": 4,
            "engines_available": 0,
        }
        rag_resp = MagicMock(status_code=200)
        rag_resp.json.return_value = {"status": "ok"}
        ollama_resp = MagicMock(status_code=200)
        ollama_resp.json.side_effect = ValueError("not json")
        mock_get.side_effect = [cas_resp, rag_resp, ollama_resp]

        result = self.runner.check_external_health()

        assert result["all_healthy"] is False
        assert result["deps"]["cas"]["healthy"] is False
        assert result["deps"]["cas"]["reason"] == "no_engines_available"
        assert result["deps"]["cas"]["engines_available"] == 0

    @patch("services.orchestrator.pipeline.requests.get")
    def test_rag_open_circuit_breaker_marks_unhealthy(self, mock_get):
        cas_resp = MagicMock(status_code=200)
        cas_resp.json.return_value = {"status": "ok", "engines_available": 2}
        rag_resp = MagicMock(status_code=200)
        rag_resp.json.return_value = {
            "status": "ok",
            "version": "3.3-smart",
            "circuit_breaker": {"state": "open"},
        }
        ollama_resp = MagicMock(status_code=200)
        ollama_resp.json.side_effect = ValueError("not json")
        mock_get.side_effect = [cas_resp, rag_resp, ollama_resp]

        result = self.runner.check_external_health()

        assert result["all_healthy"] is False
        assert result["deps"]["rag"]["healthy"] is False
        assert result["deps"]["rag"]["reason"] == "circuit_breaker_open"
        assert result["deps"]["rag"]["version"] == "3.3-smart"


class TestPreflightInHandleRun:
    """Tests for preflight check integration in handle_run()."""

    @patch("threading.Thread")
    @patch(
        "services.orchestrator.pipeline.PipelineRunner._generate_run_id",
        return_value="run-test-123",
    )
    def test_preflight_blocks_when_needed_dep_down(self, _gen_id, _thread):
        """CAS down + stages=5 (includes validator) → 503."""
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.runner = MagicMock()
        handler.runner._resolve_stages.return_value = [
            ("discovery", 8770),
            ("analyzer", 8771),
            ("extractor", 8772),
            ("validator", 8773),
            ("codegen", 8774),
        ]
        handler.runner.check_external_health.return_value = {
            "all_healthy": False,
            "deps": {
                "cas": {"url": "http://localhost:8769", "healthy": False},
                "rag": {"url": "http://localhost:8767", "healthy": True},
                "ollama": {"url": "http://localhost:11434", "healthy": True},
            },
        }
        handler.send_error_json = MagicMock()
        handler.send_json = MagicMock()

        result = handler.handle_run({"query": "test", "stages": 5})

        assert result is None
        handler.send_error_json.assert_called_once()
        args = handler.send_error_json.call_args[0]
        assert "cas" in args[0]
        assert args[1] == "PREFLIGHT_FAILED"
        assert args[2] == 503
        _thread.assert_not_called()

    @patch("threading.Thread")
    @patch(
        "services.orchestrator.pipeline.PipelineRunner._generate_run_id",
        return_value="run-test-stage-aware",
    )
    def test_preflight_allows_when_down_dep_not_needed(self, _gen_id, mock_thread):
        """CAS down but stages=2 (discovery+analyzer only) → 202."""
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.runner = MagicMock()
        handler.runner._resolve_stages.return_value = [
            ("discovery", 8770),
            ("analyzer", 8771),
        ]
        handler.runner.check_external_health.return_value = {
            "all_healthy": False,
            "deps": {
                "cas": {"url": "http://localhost:8769", "healthy": False},
                "rag": {"url": "http://localhost:8767", "healthy": True},
                "ollama": {"url": "http://localhost:11434", "healthy": True},
            },
        }
        handler.send_json = MagicMock()

        handler.handle_run({"query": "test", "stages": 2})

        # No external deps needed for discovery+analyzer → no health check
        handler.runner.check_external_health.assert_not_called()
        handler.send_json.assert_called_once_with(
            {"run_id": "run-test-stage-aware", "status": "running"},
            status=202,
        )
        mock_thread.assert_called_once()

    @patch("threading.Thread")
    @patch(
        "services.orchestrator.pipeline.PipelineRunner._generate_run_id",
        return_value="run-test-456",
    )
    def test_preflight_passes_when_all_healthy(self, _gen_id, mock_thread):
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.runner = MagicMock()
        handler.runner._resolve_stages.return_value = [
            ("discovery", 8770),
            ("analyzer", 8771),
            ("extractor", 8772),
            ("validator", 8773),
            ("codegen", 8774),
        ]
        handler.runner.check_external_health.return_value = {
            "all_healthy": True,
            "deps": {
                "cas": {"url": "http://localhost:8769", "healthy": True},
                "rag": {"url": "http://localhost:8767", "healthy": True},
                "ollama": {"url": "http://localhost:11434", "healthy": True},
            },
        }
        handler.send_json = MagicMock()

        handler.handle_run({"query": "test", "stages": 5})

        handler.send_json.assert_called_once_with(
            {"run_id": "run-test-456", "status": "running"},
            status=202,
        )
        mock_thread.assert_called_once()

    @patch("threading.Thread")
    @patch(
        "services.orchestrator.pipeline.PipelineRunner._generate_run_id",
        return_value="run-test-789",
    )
    def test_preflight_skipped_with_skip_preflight(self, _gen_id, mock_thread):
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.runner = MagicMock()
        handler.send_json = MagicMock()

        handler.handle_run({"query": "test", "stages": 5, "skip_preflight": True})

        handler.send_json.assert_called_once_with(
            {"run_id": "run-test-789", "status": "running"},
            status=202,
        )
        # Neither _resolve_stages nor check_external_health should be called
        handler.runner.check_external_health.assert_not_called()

    @patch("threading.Thread")
    @patch(
        "services.orchestrator.pipeline.PipelineRunner._generate_run_id",
        return_value="run-test-rag",
    )
    def test_preflight_blocks_when_rag_down_for_extractor(self, _gen_id, _thread):
        """RAG down + stages include extractor → 503."""
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.runner = MagicMock()
        handler.runner._resolve_stages.return_value = [
            ("discovery", 8770),
            ("analyzer", 8771),
            ("extractor", 8772),
        ]
        handler.runner.check_external_health.return_value = {
            "all_healthy": False,
            "deps": {
                "cas": {"url": "http://localhost:8769", "healthy": True},
                "rag": {"url": "http://localhost:8767", "healthy": False},
                "ollama": {"url": "http://localhost:11434", "healthy": True},
            },
        }
        handler.send_error_json = MagicMock()

        result = handler.handle_run({"query": "test", "stages": 3})

        assert result is None
        handler.send_error_json.assert_called_once()
        assert "rag" in handler.send_error_json.call_args[0][0]

    @patch("threading.Thread")
    @patch(
        "services.orchestrator.pipeline.PipelineRunner._generate_run_id",
        return_value="run-test-rag-reason",
    )
    def test_preflight_surfaces_dependency_reason(self, _gen_id, _thread):
        handler = OrchestratorHandler.__new__(OrchestratorHandler)
        handler.runner = MagicMock()
        handler.runner._resolve_stages.return_value = [
            ("discovery", 8770),
            ("analyzer", 8771),
            ("extractor", 8772),
        ]
        handler.runner.check_external_health.return_value = {
            "all_healthy": False,
            "deps": {
                "cas": {"url": "http://localhost:8769", "healthy": True},
                "rag": {
                    "url": "http://localhost:8767",
                    "healthy": False,
                    "reason": "circuit_breaker_open",
                },
                "ollama": {"url": "http://localhost:11434", "healthy": True},
            },
        }
        handler.send_error_json = MagicMock()

        result = handler.handle_run({"query": "test", "stages": 3})

        assert result is None
        handler.send_error_json.assert_called_once()
        assert "rag (circuit_breaker_open)" in handler.send_error_json.call_args[0][0]


class TestServicesHealthIncludesExternal:
    """Tests that /status/services response includes external deps."""

    @patch("services.orchestrator.pipeline.requests.get")
    def test_status_services_includes_external(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "ok"}
        mock_get.return_value = mock_resp

        runner = PipelineRunner.__new__(PipelineRunner)
        runner.db_path = ":memory:"
        result = runner.get_services_health()

        assert "external" in result
        assert "deps" in result["external"]
        assert "cas" in result["external"]["deps"]
        assert "rag" in result["external"]["deps"]
        assert "ollama" in result["external"]["deps"]


class TestExternalDepsConstant:
    """Tests for the EXTERNAL_DEPS module constant."""

    def test_has_three_deps(self):
        assert len(EXTERNAL_DEPS) == 3

    def test_dep_names(self):
        names = [d[0] for d in EXTERNAL_DEPS]
        assert names == ["cas", "rag", "ollama"]

    def test_dep_health_paths(self):
        paths = [d[2] for d in EXTERNAL_DEPS]
        assert paths == ["/health", "/health", "/"]


class TestStageExternalDeps:
    """Tests for stage-to-external-dep mapping."""

    def test_extractor_needs_rag(self):
        assert "rag" in STAGE_EXTERNAL_DEPS["extractor"]

    def test_validator_needs_cas(self):
        assert "cas" in STAGE_EXTERNAL_DEPS["validator"]

    def test_codegen_has_no_hard_deps(self):
        assert "codegen" not in STAGE_EXTERNAL_DEPS

    def test_discovery_has_no_deps(self):
        assert "discovery" not in STAGE_EXTERNAL_DEPS

    def test_analyzer_has_no_deps(self):
        assert "analyzer" not in STAGE_EXTERNAL_DEPS
