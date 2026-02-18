"""Shared LLM client functions for the research pipeline.

Provider functions + a fallback_chain orchestrator.
Each function is ~30 LOC, easy to test/mock individually.

CLI providers (claude_cli, codex_cli, gemini_cli) are data-driven via
shared/cli_providers.json — to add a new CLI or fix flag changes, update
the JSON config only, zero Python changes needed.

Used by:
- Analyzer service (Gemini-first fallback: gemini_cli → gemini_sdk → ollama)
- Codegen service (Ollama-first fallback: ollama → gemini_sdk → gemini_cli)

Extracted from services/analyzer/llm.py in Phase 18.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import urllib.request
from pathlib import Path

from shared.config import LLM_SEED, LLM_TEMPERATURE

logger = logging.getLogger(__name__)

DEFAULT_FALLBACK_ORDER = os.environ.get(
    "RP_LLM_FALLBACK_ORDER", "gemini_cli,openrouter,ollama"
).split(",")


# ---------------------------------------------------------------------------
# CLI provider registry (data-driven)
# ---------------------------------------------------------------------------

_CLI_CONFIGS: dict[str, dict] | None = None


def _load_cli_configs() -> dict[str, dict]:
    """Load CLI provider configs from cli_providers.json (cached)."""
    global _CLI_CONFIGS
    if _CLI_CONFIGS is not None:
        return _CLI_CONFIGS
    config_path = Path(__file__).parent / "cli_providers.json"
    with open(config_path) as f:
        configs: dict[str, dict] = json.load(f)
    _CLI_CONFIGS = configs
    return configs


def call_cli(
    provider_name: str,
    prompt: str,
    system: str | None = None,
    model: str | None = None,
    timeout: int | None = None,
) -> str:
    """Call a CLI provider using its JSON config.

    Args:
        provider_name: Key in cli_providers.json (e.g. "claude_cli").
        prompt: User prompt text.
        system: System instruction text.
        model: Model override (uses config default if None).
        timeout: Timeout override in seconds.

    Returns:
        Raw response text.

    Raises:
        RuntimeError: On non-zero exit, timeout, or parse error.
        KeyError: If provider_name not found in config.
    """
    configs = _load_cli_configs()
    cfg = configs[provider_name]

    cmd = list(cfg["cmd"])

    # Model flag
    if cfg.get("model_flag") and (model or cfg.get("default_model")):
        cmd.extend([cfg["model_flag"], model or cfg["default_model"]])

    # System flag
    if cfg.get("system_flag") and system:
        cmd.extend([cfg["system_flag"], system])

    # Extra args
    if cfg.get("extra_args"):
        cmd.extend(cfg["extra_args"])

    # Input mode: "arg" appends prompt to cmd, "stdin" pipes it
    input_text = None
    if cfg["input_mode"] == "arg":
        # For gemini_cli, system is prepended to prompt (no system flag)
        if not cfg.get("system_flag") and system:
            cmd.append(f"{system}\n\n---\n\n{prompt}")
        else:
            cmd.append(prompt)
    else:
        input_text = prompt

    # Timeout
    if timeout is None:
        timeout = int(os.environ.get(
            cfg["timeout_env"], str(cfg["default_timeout"])
        ))

    # Build env — pass GOOGLE_API_KEY for gemini_cli
    env = dict(os.environ)
    if provider_name == "gemini_cli":
        env["GOOGLE_API_KEY"] = _get_gemini_api_key()

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        input=input_text,
        stdin=subprocess.DEVNULL if input_text is None else None,
        env=env,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"{provider_name} exit {result.returncode}: {result.stderr[:200]}"
        )

    output = result.stdout.strip()

    # Parse output based on format
    if cfg["output_format"] == "json":
        data = json.loads(output)
        if data.get("error"):
            raise RuntimeError(
                f"{provider_name} API error: {data['error'].get('message', data['error'])}"
            )
        response_text = data.get("response", "")
        return _strip_markdown_fences(response_text)

    return _strip_markdown_fences(output)


def call_claude_cli(
    prompt: str,
    system: str,
    model: str | None = None,
    timeout: int | None = None,
) -> str:
    """Call Claude via CLI subprocess (thin wrapper on call_cli)."""
    return call_cli("claude_cli", prompt, system, model, timeout)


def call_codex_cli(
    prompt: str,
    system: str,
    model: str | None = None,
    timeout: int | None = None,
) -> str:
    """Call Codex via CLI subprocess (thin wrapper on call_cli)."""
    return call_cli("codex_cli", prompt, system, model, timeout)


def _get_gemini_api_key() -> str:
    """Load Gemini API key from environment.

    Returns:
        API key string.

    Raises:
        RuntimeError: If key not found.
    """
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")
    return key


def _strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences from LLM response.

    Handles ```json ... ``` and ``` ... ``` patterns.
    """
    stripped = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
    stripped = re.sub(r"\n?```\s*$", "", stripped)
    return stripped.strip()


def call_gemini_cli(
    prompt: str,
    system: str,
    model: str = "gemini-2.5-flash",
    timeout: int = int(os.environ.get("RP_LLM_TIMEOUT_GEMINI_CLI", "120")),
) -> str:
    """Call Gemini via CLI subprocess (delegates to call_cli for backward compat)."""
    return call_cli("gemini_cli", prompt, system, model, timeout)


def call_gemini_sdk(
    prompt: str,
    system: str,
    model: str = "gemini-2.5-flash",
    timeout: float = float(os.environ.get("RP_LLM_TIMEOUT_GEMINI_SDK", "60")),
    temperature: float = LLM_TEMPERATURE,
) -> str:
    """Call Gemini via Python SDK.

    Args:
        prompt: User prompt text.
        system: System instruction text.
        model: Gemini model name.
        timeout: HTTP timeout in seconds.
        temperature: Sampling temperature (0 = deterministic).

    Returns:
        Raw response text from Gemini SDK.

    Raises:
        RuntimeError: On API error or timeout.
    """
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=_get_gemini_api_key(),
        http_options=types.HttpOptions(client_args={"timeout": timeout}),
    )
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=4096,
            response_mime_type="application/json",
            seed=LLM_SEED,
        ),
    )
    if response.text is None:
        raise RuntimeError("Gemini SDK returned empty response")
    return response.text


def call_openrouter(
    prompt: str,
    system: str,
    model: str = "google/gemini-2.5-flash",
    timeout: int = int(os.environ.get("RP_LLM_TIMEOUT_OPENROUTER", "60")),
    temperature: float = LLM_TEMPERATURE,
) -> str:
    """Call OpenRouter API (OpenAI-compatible).

    Args:
        prompt: User prompt text.
        system: System instruction text.
        model: Model identifier on OpenRouter.
        timeout: HTTP timeout in seconds.
        temperature: Sampling temperature (0 = deterministic).

    Returns:
        Raw response text.

    Raises:
        RuntimeError: On API error, missing key, or timeout.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set")

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": 4096,
        "seed": LLM_SEED,
    }).encode()

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())

    if "error" in data:
        raise RuntimeError(f"OpenRouter error: {data['error']}")

    return data["choices"][0]["message"]["content"]


def call_ollama(
    prompt: str,
    system: str,
    model: str = "qwen3:8b",
    timeout: int = int(os.environ.get("RP_LLM_TIMEOUT_OLLAMA", "600")),
    base_url: str = "http://localhost:11434",
    format: str | dict = "json",
    options: dict | None = None,
    temperature: float = LLM_TEMPERATURE,
) -> str:
    """Call Ollama local LLM.

    Args:
        prompt: User prompt text.
        system: System instruction text.
        model: Ollama model name.
        timeout: HTTP timeout in seconds.
        base_url: Ollama server URL.
        format: Output format — "json" for free-form JSON, or a
            dict (e.g. model_json_schema()) for structured output.
        options: Ollama generation options (temperature, num_predict,
            num_ctx, etc.). If provided, overrides temperature param.
        temperature: Sampling temperature (0 = deterministic).
            Ignored if options is provided.

    Returns:
        Raw response text from Ollama.

    Raises:
        RuntimeError: On connection error, timeout, or non-200 response.
    """
    if options is None:
        options = {"temperature": temperature, "seed": LLM_SEED, "num_predict": 4096}

    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "system": system,
        "format": format,
        "stream": False,
        "keep_alive": "10m",
        "options": options,
    }).encode()

    req = urllib.request.Request(
        f"{base_url}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Ollama HTTP {resp.status}")
        data = json.loads(resp.read())

    if "error" in data:
        raise RuntimeError(f"Ollama error: {data['error']}")

    return data["response"]


def fallback_chain(
    prompt: str,
    system: str,
    order: list[str] | None = None,
    temperature: float | None = None,
) -> tuple[str, str]:
    """Try LLM providers in specified order.

    Args:
        prompt: User prompt text.
        system: System instruction text.
        order: Provider order. Default None uses
            ["gemini_cli", "gemini_sdk", "ollama"] (Analyzer default).
            Codegen uses ["ollama", "gemini_sdk", "gemini_cli"].
        temperature: Override temperature for all providers.
            None uses each provider's default (LLM_TEMPERATURE).
            Note: gemini_cli does not support temperature control.

    Returns:
        Tuple of (response_text, provider_name).

    Raises:
        RuntimeError: If all providers fail.
    """
    if order is None:
        order = DEFAULT_FALLBACK_ORDER

    provider_funcs = {
        "gemini_cli": call_gemini_cli,
        "gemini_sdk": call_gemini_sdk,
        "openrouter": call_openrouter,
        "ollama": call_ollama,
        "claude_cli": call_claude_cli,
        "codex_cli": call_codex_cli,
    }

    # Providers that accept temperature kwarg
    _temp_providers = {"gemini_sdk", "openrouter", "ollama"}

    errors: list[str] = []
    for name in order:
        func = provider_funcs.get(name)
        if func is None:
            errors.append(f"{name}: unknown provider")
            continue
        try:
            kwargs: dict = {}
            if temperature is not None and name in _temp_providers:
                kwargs["temperature"] = temperature
            result = func(prompt, system, **kwargs)
            return (result, name)
        except Exception as e:
            logger.warning("LLM fallback: %s failed: %s", name, e)
            errors.append(f"{name}: {e}")

    raise RuntimeError(f"All LLM providers failed: {'; '.join(errors)}")
