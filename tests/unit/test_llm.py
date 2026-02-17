"""Unit tests for shared/llm.py — LLM temperature configuration and provider calls."""

from __future__ import annotations

import importlib
import json
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
