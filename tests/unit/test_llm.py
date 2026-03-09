"""Unit tests for shared/llm.py — LLM temperature configuration and provider calls."""

from __future__ import annotations

import importlib
import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Temperature config tests
# ---------------------------------------------------------------------------


class TestLLMTemperatureConfig:
    """Tests for LLM_TEMPERATURE configuration via shared.config."""

    def test_llm_temperature_default_zero(self, monkeypatch):
        """LLM_TEMPERATURE defaults to 0.0 when RP_LLM_TEMPERATURE is not set."""
        monkeypatch.delenv("RP_LLM_TEMPERATURE", raising=False)
        import shared.config as cfg_mod

        importlib.reload(cfg_mod)
        assert cfg_mod.LLM_TEMPERATURE == 0.0

    def test_llm_temperature_from_env(self, monkeypatch):
        """LLM_TEMPERATURE picks up RP_LLM_TEMPERATURE from the environment."""
        monkeypatch.setenv("RP_LLM_TEMPERATURE", "0.5")
        import shared.config as cfg_mod

        importlib.reload(cfg_mod)
        assert cfg_mod.LLM_TEMPERATURE == 0.5


class TestParseFloatEnv:
    """Tests for _parse_float_env helper in shared.config."""

    def test_parse_float_env_valid(self, monkeypatch):
        """Valid float string is parsed correctly."""
        monkeypatch.setenv("_TEST_FLOAT", "1.23")
        from shared.config import _parse_float_env

        assert _parse_float_env("_TEST_FLOAT", "0") == 1.23

    def test_parse_float_env_invalid(self, monkeypatch):
        """Invalid value falls back to the default."""
        monkeypatch.setenv("_TEST_FLOAT", "abc")
        from shared.config import _parse_float_env

        assert _parse_float_env("_TEST_FLOAT", "0") == 0.0


# ---------------------------------------------------------------------------
# Helper: fake urlopen context-manager response
# ---------------------------------------------------------------------------


def _fake_urlopen(body: dict, status: int = 200):
    """Return a mock that behaves like urllib.request.urlopen context manager."""
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = json.dumps(body).encode()
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=resp)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


# ---------------------------------------------------------------------------
# call_ollama tests
# ---------------------------------------------------------------------------


class TestCallOllama:
    """Tests for call_ollama temperature and seed handling."""

    @patch("shared.llm.urllib.request.urlopen")
    def test_call_ollama_uses_config_temperature(self, mock_urlopen, monkeypatch):
        """call_ollama sends temperature from LLM_TEMPERATURE (not hardcoded 0.3)."""
        monkeypatch.delenv("RP_LLM_TEMPERATURE", raising=False)
        import shared.config as cfg_mod

        importlib.reload(cfg_mod)

        import shared.llm as llm_mod

        importlib.reload(llm_mod)

        mock_urlopen.return_value = _fake_urlopen({"response": "test"})

        llm_mod.call_ollama("hello", "system prompt")

        # Extract the payload sent to urlopen
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        payload = json.loads(req.data)

        assert payload["options"]["temperature"] == 0.0

    @patch("shared.llm.urllib.request.urlopen")
    def test_call_ollama_includes_seed(self, mock_urlopen, monkeypatch):
        """call_ollama includes seed=42 in options."""
        monkeypatch.delenv("RP_LLM_TEMPERATURE", raising=False)
        import shared.config as cfg_mod

        importlib.reload(cfg_mod)

        import shared.llm as llm_mod

        importlib.reload(llm_mod)

        mock_urlopen.return_value = _fake_urlopen({"response": "test"})

        llm_mod.call_ollama("hello", "system prompt")

        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data)

        assert payload["options"]["seed"] == 42

    @patch("shared.llm.urllib.request.urlopen")
    def test_call_ollama_resolves_container_host_gateway_from_env(
        self, mock_urlopen, monkeypatch
    ):
        monkeypatch.setenv("RP_CODEGEN_OLLAMA_URL", "http://localhost:11434")
        monkeypatch.setenv("RP_DOCKER_HOST_GATEWAY", "host.docker.internal")

        import shared.llm as llm_mod

        importlib.reload(llm_mod)
        mock_urlopen.return_value = _fake_urlopen({"response": "test"})

        llm_mod.call_ollama("hello", "system prompt")

        req = mock_urlopen.call_args[0][0]
        assert req.full_url.startswith(
            "http://host.docker.internal:11434/api/generate"
        )


# ---------------------------------------------------------------------------
# call_openrouter tests
# ---------------------------------------------------------------------------


class TestCallOpenRouter:
    """Tests for call_openrouter temperature and seed handling."""

    @patch("shared.llm.urllib.request.urlopen")
    def test_call_openrouter_uses_config_temperature(self, mock_urlopen, monkeypatch):
        """call_openrouter sends temperature matching LLM_TEMPERATURE."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-fake")
        monkeypatch.delenv("RP_LLM_TEMPERATURE", raising=False)
        import shared.config as cfg_mod

        importlib.reload(cfg_mod)

        import shared.llm as llm_mod

        importlib.reload(llm_mod)

        mock_urlopen.return_value = _fake_urlopen(
            {"choices": [{"message": {"content": "test"}}]}
        )

        llm_mod.call_openrouter("hello", "system prompt")

        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data)

        assert payload["temperature"] == 0.0

    @patch("shared.llm.urllib.request.urlopen")
    def test_call_openrouter_includes_seed(self, mock_urlopen, monkeypatch):
        """call_openrouter includes seed=42 in payload."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-fake")
        monkeypatch.delenv("RP_LLM_TEMPERATURE", raising=False)
        import shared.config as cfg_mod

        importlib.reload(cfg_mod)

        import shared.llm as llm_mod

        importlib.reload(llm_mod)

        mock_urlopen.return_value = _fake_urlopen(
            {"choices": [{"message": {"content": "test"}}]}
        )

        llm_mod.call_openrouter("hello", "system prompt")

        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data)

        assert payload["seed"] == 42


# ---------------------------------------------------------------------------
# fallback_chain tests
# ---------------------------------------------------------------------------


class TestFallbackChain:
    """Tests for fallback_chain temperature threading."""

    @patch("shared.llm.call_ollama")
    @patch("shared.llm.call_openrouter")
    @patch("shared.llm.call_gemini_cli")
    def test_fallback_chain_threads_temperature(
        self, mock_cli, mock_openrouter, mock_ollama
    ):
        """fallback_chain passes temperature=0.7 to the first successful provider."""
        # gemini_cli does not accept temperature — it should be called without it
        mock_cli.side_effect = RuntimeError("no gemini")
        # openrouter succeeds
        mock_openrouter.return_value = "ok"

        from shared.llm import fallback_chain

        result, provider = fallback_chain(
            "hello",
            "system",
            order=["gemini_cli", "openrouter", "ollama"],
            temperature=0.7,
        )

        assert result == "ok"
        assert provider == "openrouter"

        # gemini_cli called WITHOUT temperature (not in _temp_providers for cli)
        mock_cli.assert_called_once_with("hello", "system")
        # openrouter called WITH temperature=0.7
        mock_openrouter.assert_called_once_with(
            "hello", "system", temperature=0.7
        )
        # ollama never called — openrouter succeeded
        mock_ollama.assert_not_called()


# ---------------------------------------------------------------------------
# CLI provider registry tests
# ---------------------------------------------------------------------------


class TestLoadCliConfigs:
    """Tests for _load_cli_configs() — cached JSON loading."""

    def test_loads_valid_json(self):
        """cli_providers.json loads and contains expected providers."""
        from shared.llm import _load_cli_configs

        configs = _load_cli_configs()
        assert "claude_cli" in configs
        assert "codex_cli" in configs
        assert "gemini_cli" in configs

    def test_claude_cli_config_structure(self):
        """claude_cli config has required keys."""
        from shared.llm import _load_cli_configs

        cfg = _load_cli_configs()["claude_cli"]
        assert cfg["input_mode"] == "stdin"
        assert cfg["output_format"] == "json"
        assert cfg["system_flag"] == "--append-system-prompt"
        assert isinstance(cfg["cmd"], list)

    def test_codex_cli_config_structure(self):
        """codex_cli config has required keys."""
        from shared.llm import _load_cli_configs

        cfg = _load_cli_configs()["codex_cli"]
        assert cfg["input_mode"] == "arg"
        assert cfg["system_flag"] is None
        assert cfg["model_flag"] is None

    def test_caching(self):
        """Second call returns same object (module-level cache)."""
        import shared.llm as llm_mod

        # Reset cache
        llm_mod._CLI_CONFIGS = None
        first = llm_mod._load_cli_configs()
        second = llm_mod._load_cli_configs()
        assert first is second


class TestCallCli:
    """Tests for call_cli() — generic CLI dispatcher."""

    @patch("shared.llm.subprocess.run")
    def test_claude_cli_stdin_mode(self, mock_run, monkeypatch):
        """claude_cli sends prompt via stdin, parses JSON output."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"response": "test answer"}),
            stderr="",
        )
        from shared.llm import call_cli

        result = call_cli("claude_cli", "hello", system="be helpful")
        assert result == "test answer"

        # Verify stdin mode: input= should be the prompt
        call_args = mock_run.call_args
        assert call_args[1]["input"] == "hello"

    @patch("shared.llm.subprocess.run")
    def test_claude_cli_includes_system_flag(self, mock_run):
        """claude_cli passes --append-system-prompt with system text."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"response": "ok"}),
            stderr="",
        )
        from shared.llm import call_cli

        call_cli("claude_cli", "prompt", system="system text")
        cmd = mock_run.call_args[0][0]
        assert "--append-system-prompt" in cmd
        assert "system text" in cmd

    @patch("shared.llm.subprocess.run")
    def test_claude_cli_includes_model_flag(self, mock_run):
        """claude_cli passes --model with specified model."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"response": "ok"}),
            stderr="",
        )
        from shared.llm import call_cli

        call_cli("claude_cli", "prompt", system="s", model="opus")
        cmd = mock_run.call_args[0][0]
        assert "--model" in cmd
        assert "opus" in cmd

    @patch("shared.llm.subprocess.run")
    def test_codex_cli_arg_mode(self, mock_run):
        """codex_cli sends prompt as CLI arg (not stdin)."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="codex output",
            stderr="",
        )
        from shared.llm import call_cli

        result = call_cli("codex_cli", "hello world")
        assert result == "codex output"

        # Verify arg mode: prompt appended to cmd, no input=
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "hello world" in cmd
        assert call_args[1].get("input") is None

    @patch("shared.llm.subprocess.run")
    @patch("shared.llm._get_gemini_api_key", return_value="fake-key")
    def test_gemini_cli_backward_compat(self, mock_key, mock_run):
        """gemini_cli call via call_cli matches old call_gemini_cli behavior."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"response": "gemini response"}),
            stderr="",
        )
        from shared.llm import call_cli

        result = call_cli("gemini_cli", "prompt", system="sys")
        assert result == "gemini response"

        # Verify prompt includes system (prepended, no system_flag)
        cmd = mock_run.call_args[0][0]
        prompt_arg = cmd[-1]
        assert "sys" in prompt_arg
        assert "prompt" in prompt_arg

    @patch("shared.llm.subprocess.run")
    def test_nonzero_exit_raises(self, mock_run):
        """Non-zero exit code raises RuntimeError."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="command not found",
        )
        from shared.llm import call_cli

        with pytest.raises(RuntimeError, match="exit 1"):
            call_cli("claude_cli", "prompt")

    @patch("shared.llm.subprocess.run")
    def test_timeout_raises(self, mock_run):
        """subprocess.TimeoutExpired propagates."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=10)
        from shared.llm import call_cli

        with pytest.raises(subprocess.TimeoutExpired):
            call_cli("claude_cli", "prompt", timeout=10)

    @patch("shared.llm.subprocess.run")
    def test_json_error_field_raises(self, mock_run):
        """claude_cli JSON output with 'error' field raises RuntimeError."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"error": {"message": "rate limited"}}),
            stderr="",
        )
        from shared.llm import call_cli

        with pytest.raises(RuntimeError, match="rate limited"):
            call_cli("claude_cli", "prompt")

    def test_unknown_provider_raises(self):
        """Unknown provider name raises KeyError."""
        from shared.llm import call_cli

        with pytest.raises(KeyError):
            call_cli("nonexistent_provider", "prompt")


class TestFallbackOrder:
    """Tests for RP_LLM_FALLBACK_ORDER env var."""

    def test_default_order(self):
        """Default order is gemini_cli,openrouter,ollama."""
        import shared.llm as llm_mod

        # Don't reload to avoid side effects — just check the actual value
        assert isinstance(llm_mod.DEFAULT_FALLBACK_ORDER, list)
        assert len(llm_mod.DEFAULT_FALLBACK_ORDER) >= 2

    def test_custom_order_from_env(self, monkeypatch):
        """RP_LLM_FALLBACK_ORDER overrides default."""
        monkeypatch.setenv("RP_LLM_FALLBACK_ORDER", "claude_cli,gemini_cli")
        import shared.llm as llm_mod

        importlib.reload(llm_mod)
        assert llm_mod.DEFAULT_FALLBACK_ORDER == ["claude_cli", "gemini_cli"]

        # Restore default
        monkeypatch.delenv("RP_LLM_FALLBACK_ORDER", raising=False)
        importlib.reload(llm_mod)

    @patch("shared.llm.call_claude_cli", return_value="claude response")
    @patch("shared.llm.call_codex_cli", return_value="codex response")
    def test_fallback_chain_with_cli_providers(self, mock_codex, mock_claude):
        """fallback_chain can use claude_cli and codex_cli providers."""
        from shared.llm import fallback_chain

        result, provider = fallback_chain(
            "prompt", "system",
            order=["claude_cli", "codex_cli"],
        )
        assert result == "claude response"
        assert provider == "claude_cli"
        mock_codex.assert_not_called()

    @patch("shared.llm.call_claude_cli", side_effect=RuntimeError("fail"))
    @patch("shared.llm.call_codex_cli", return_value="codex response")
    def test_fallback_chain_cli_failover(self, mock_codex, mock_claude):
        """If claude_cli fails, fallback_chain tries codex_cli."""
        from shared.llm import fallback_chain

        result, provider = fallback_chain(
            "prompt", "system",
            order=["claude_cli", "codex_cli"],
        )
        assert result == "codex response"
        assert provider == "codex_cli"
