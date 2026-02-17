"""Shared LLM client functions for the research pipeline.

Three independent client functions + a fallback_chain orchestrator.
Each function is ~30 LOC, easy to test/mock individually.

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

from shared.config import LLM_SEED, LLM_TEMPERATURE

logger = logging.getLogger(__name__)

DEFAULT_FALLBACK_ORDER = ["gemini_cli", "openrouter", "ollama"]


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
    """Call Gemini via CLI subprocess.

    Args:
        prompt: User prompt text.
        system: System instruction text.
        model: Gemini model name.
        timeout: Subprocess timeout in seconds.

    Returns:
        Raw response text from Gemini.

    Raises:
        RuntimeError: On non-zero exit, API error, or timeout.
    """
    full_prompt = f"{system}\n\n---\n\n{prompt}"

    result = subprocess.run(
        ["gemini", "-p", full_prompt, "-m", model,
         "--output-format", "json", "-e", "none"],
        capture_output=True,
        text=True,
        timeout=timeout,
        stdin=subprocess.DEVNULL,
        env={**os.environ, "GOOGLE_API_KEY": _get_gemini_api_key()},
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Gemini CLI exit {result.returncode}: {result.stderr[:200]}"
        )

    data = json.loads(result.stdout)
    if data.get("error"):
        raise RuntimeError(
            f"Gemini API error: {data['error'].get('message', 'unknown')}"
        )

    response_text = data.get("response", "")
    return _strip_markdown_fences(response_text)


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
