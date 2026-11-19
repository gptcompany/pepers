"""Integration tests for docker-compose.yml production hardening (Phase 45).

Validates log rotation, memory limits, stop_grace_period, and init settings
by parsing the resolved Docker Compose config.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

SERVICES = ["discovery", "analyzer", "extractor", "validator", "codegen", "orchestrator", "mcp"]
REGULAR_SERVICES = [s for s in SERVICES if s != "orchestrator"]
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_compose_config(env_overrides: dict[str, str] | None = None) -> dict:
    """Parse resolved docker-compose.yml via docker compose config."""
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    result = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
    )
    assert result.returncode == 0, f"docker compose config failed: {result.stderr}"
    return json.loads(result.stdout)


def _parse_duration_s(value) -> int:
    """Parse Docker duration string (e.g. '10s', '20s') or nanoseconds int to seconds."""
    if isinstance(value, (int, float)):
        return value // 1_000_000_000
    s = str(value).strip().lower()
    if s.endswith("s"):
        return int(s[:-1])
    if s.endswith("m"):
        return int(s[:-1]) * 60
    return int(s)


@pytest.fixture(scope="module")
def compose_config():
    """Parse resolved docker-compose.yml via docker compose config."""
    return _load_compose_config()


class TestLogRotation:
    """DEP-01: No single container log exceeds 10MB."""

    def test_all_services_have_json_file_driver(self, compose_config):
        for name in SERVICES:
            svc = compose_config["services"][name]
            assert svc["logging"]["driver"] == "json-file", f"{name} missing json-file logging"

    def test_all_services_max_size_10m(self, compose_config):
        for name in SERVICES:
            opts = compose_config["services"][name]["logging"]["options"]
            assert opts["max-size"] == "10m", f"{name} max-size != 10m"

    def test_all_services_max_file_3(self, compose_config):
        for name in SERVICES:
            opts = compose_config["services"][name]["logging"]["options"]
            assert opts["max-file"] == "3", f"{name} max-file != 3"


class TestMemoryLimits:
    """DEP-02: Memory limits enforced by Docker."""

    def test_regular_services_512m(self, compose_config):
        for name in REGULAR_SERVICES:
            mem = compose_config["services"][name]["deploy"]["resources"]["limits"]["memory"]
            assert int(mem) == 536870912, f"{name} memory limit != 512MB (got {mem})"

    def test_orchestrator_1g(self, compose_config):
        mem = compose_config["services"]["orchestrator"]["deploy"]["resources"]["limits"]["memory"]
        assert int(mem) == 1073741824, f"orchestrator memory limit != 1GB (got {mem})"


class TestGracefulShutdown:
    """DEP-04: docker compose down completes within 30s."""

    def test_regular_services_grace_10s(self, compose_config):
        for name in REGULAR_SERVICES:
            grace = compose_config["services"][name].get("stop_grace_period")
            assert grace is not None, f"{name} missing stop_grace_period"
            assert _parse_duration_s(grace) <= 10, f"{name} stop_grace_period > 10s"

    def test_orchestrator_grace_20s(self, compose_config):
        grace = compose_config["services"]["orchestrator"].get("stop_grace_period")
        assert grace is not None, "orchestrator missing stop_grace_period"
        assert _parse_duration_s(grace) <= 20, "orchestrator stop_grace_period > 20s"


class TestInitProcess:
    """Best practice: init: true for proper signal forwarding and zombie reaping."""

    def test_all_services_init_true(self, compose_config):
        for name in SERVICES:
            init = compose_config["services"][name].get("init", False)
            assert init is True, f"{name} missing init: true"


class TestNoSwap:
    """F-775 (limiti-risorse-calcolo-agenti): memswap_limit == limite di memoria, niente swap."""

    def test_memswap_limit_equals_memory_limit(self, compose_config):
        for name in SERVICES:
            svc = compose_config["services"][name]
            mem = int(svc["deploy"]["resources"]["limits"]["memory"])
            assert int(svc.get("memswap_limit", 0)) == mem, f"{name} memswap_limit != memory limit"

    def test_host_network_with_explicit_loopback_bind(self, compose_config):
        """Decisione dell'operatore (19/11): rete host, niente ports/extra_hosts, bind su 127.0.0.1."""
        for name in SERVICES:
            svc = compose_config["services"][name]
            assert svc.get("network_mode") == "host", f"{name} not on host network"
            assert svc.get("pull_policy") == "build", f"{name} may reuse a pre-bind image"
            assert "ports" not in svc and "extra_hosts" not in svc, name
            assert svc["environment"]["RP_BIND_HOST"] == "127.0.0.1", name

    def test_no_gateway_rewrite_and_internal_urls_on_loopback(self, compose_config):
        internal = {"RP_DISCOVERY_URL", "RP_ANALYZER_URL", "RP_EXTRACTOR_URL", "RP_VALIDATOR_URL",
                    "RP_CODEGEN_URL", "RP_ORCHESTRATOR_URL"}
        for name in SERVICES:
            env = compose_config["services"][name]["environment"]
            assert not env.get("RP_DOCKER_HOST_GATEWAY"), f"{name} keeps the localhost rewrite active"
            for key in internal & env.keys():
                assert env[key].startswith("http://127.0.0.1:"), f"{name} {key}={env[key]}"


class TestAutoStart:
    """DEP-03: All containers restart after host reboot."""

    def test_all_services_restart_unless_stopped(self, compose_config):
        for name in SERVICES:
            restart = compose_config["services"][name].get("restart", "no")
            assert restart == "unless-stopped", (
                f"{name} restart policy is '{restart}', expected 'unless-stopped'"
            )

    def test_docker_daemon_enabled(self):
        """Docker daemon must be systemd-enabled for restart policy to work after reboot."""
        result = subprocess.run(
            ["systemctl", "is-enabled", "docker"],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "enabled", "Docker daemon not systemd-enabled"


class TestExtractorPathMapping:
    def test_compose_uses_pwd_as_legacy_project_host_dir_fallback(self):
        content = (REPO_ROOT / "docker-compose.yml").read_text()
        assert "RP_EXTRACTOR_PROJECT_HOST_DIR=${PEPERS_PROJECT_HOST_DIR:-${PWD}}" in content

    def test_extractor_project_host_dir_uses_explicit_env(self):
        config = _load_compose_config(
            {
                "PEPERS_PROJECT_HOST_DIR": "/stable/project/root",
                "PWD": "/wrong/caller/pwd",
            }
        )
        env = config["services"]["extractor"]["environment"]
        assert env["RP_EXTRACTOR_PROJECT_HOST_DIR"] == "/stable/project/root"

    def test_extractor_project_host_dir_falls_back_to_pwd_when_explicit_env_missing(self):
        config = _load_compose_config(
            {
                "PWD": "/caller/repo/root",
            }
        )
        env = config["services"]["extractor"]["environment"]
        assert env["RP_EXTRACTOR_PROJECT_HOST_DIR"] == "/caller/repo/root"

    def test_extractor_honors_legacy_rag_data_host_override(self):
        config = _load_compose_config(
            {
                "PEPERS_PROJECT_HOST_DIR": "/stable/project/root",
                "RAG_DATA_HOST": "/legacy/rag-data",
                "RAG_DATA_PATH": "",
            }
        )
        env = config["services"]["extractor"]["environment"]
        rag_volume = next(
            volume
            for volume in config["services"]["extractor"]["volumes"]
            if volume["target"] == "/rag-data"
        )

        assert env["RP_EXTRACTOR_RAG_DATA_HOST"] == "/legacy/rag-data"
        assert env["RP_EXTRACTOR_PDF_HOST_DIR"] == "/legacy/rag-data/pdfs"
        assert rag_volume["source"] == "/legacy/rag-data"


class TestAnalyzerLlmDefaults:
    def test_analyzer_prefers_oauth_and_relaxed_timeouts_by_default(self):
        config = _load_compose_config(
            {
                "RP_ANALYZER_LLM_FALLBACK_ORDER": "",
                "RP_GEMINI_CLI_USE_OAUTH": "",
                "RP_LLM_TIMEOUT_GEMINI_CLI": "",
                "RP_LLM_TIMEOUT_OLLAMA": "",
            }
        )
        env = config["services"]["analyzer"]["environment"]
        assert env["RP_ANALYZER_LLM_FALLBACK_ORDER"] == "gemini_cli,gemini_sdk"
        assert env["RP_GEMINI_CLI_USE_OAUTH"] == "true"
        assert env["RP_LLM_TIMEOUT_GEMINI_CLI"] == "60"
        assert env["RP_LLM_TIMEOUT_OLLAMA"] == "120"


class TestExtractorRagDefaults:
    def test_extractor_uses_relaxed_rag_timeouts_by_default(self):
        config = _load_compose_config(
            {
                "RP_EXTRACTOR_RAG_REQUEST_TIMEOUT": "",
                "RP_EXTRACTOR_RAG_SUBMIT_TIMEOUT": "",
                "RP_EXTRACTOR_RAG_JOB_TIMEOUT": "",
                "RP_EXTRACTOR_RAG_POLL_INTERVAL": "",
            }
        )
        env = config["services"]["extractor"]["environment"]
        assert env["RP_EXTRACTOR_RAG_REQUEST_TIMEOUT"] == "30"
        assert env["RP_EXTRACTOR_RAG_SUBMIT_TIMEOUT"] == "60"
        assert env["RP_EXTRACTOR_RAG_JOB_TIMEOUT"] == "14400"
        assert env["RP_EXTRACTOR_RAG_POLL_INTERVAL"] == "30"


class TestOrchestratorStageTimeoutDefaults:
    def test_orchestrator_uses_stage_specific_timeouts_by_default(self):
        config = _load_compose_config(
            {
                "RP_ORCHESTRATOR_ANALYZER_TIMEOUT": "",
                "RP_ORCHESTRATOR_EXTRACTOR_TIMEOUT": "",
            }
        )
        env = config["services"]["orchestrator"]["environment"]
        assert env["RP_ORCHESTRATOR_ANALYZER_TIMEOUT"] == "1800"
        assert env["RP_ORCHESTRATOR_EXTRACTOR_TIMEOUT"] == "15000"


class TestOllamaModelPassthrough:
    """F-775: il modello ollama dichiarato nell'ambiente di lancio arriva ai container che chiamano call_ollama."""

    def test_model_override_reaches_analyzer_and_codegen(self):
        config = _load_compose_config({"RP_ANALYZER_OLLAMA_MODEL": "qwen3.5:9b"})
        for name in ("analyzer", "codegen"):
            assert config["services"][name]["environment"]["RP_ANALYZER_OLLAMA_MODEL"] == "qwen3.5:9b"

    def test_model_is_versioned_in_compose_when_env_is_unset(self):
        """Una sola fonte versionata: il default del deploy sta nel compose, non solo nel .env gitignorato."""
        env = {"RP_ANALYZER_OLLAMA_MODEL": ""}
        config = _load_compose_config(env)
        for name in ("analyzer", "codegen"):
            assert config["services"][name]["environment"]["RP_ANALYZER_OLLAMA_MODEL"] == "qwen3:8b"
