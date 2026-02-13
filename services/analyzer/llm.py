"""LLM client functions for the Analyzer service.

Three independent client functions + a fallback_chain orchestrator.
Each function is ~30 LOC, easy to test/mock individually.

Fallback order: Gemini CLI → Gemini SDK → Ollama (local).
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import urllib.request

logger = logging.getLogger(__name__)


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
    timeout: int = 120,
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
    timeout: float = 30.0,
) -> str:
    """Call Gemini via Python SDK.

    Args:
        prompt: User prompt text.
        system: System instruction text.
        model: Gemini model name.
        timeout: HTTP timeout in seconds.

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
            temperature=0.3,
            max_output_tokens=500,
            response_mime_type="application/json",
        ),
    )
    if response.text is None:
        raise RuntimeError("Gemini SDK returned empty response")
    return response.text


def call_ollama(
    prompt: str,
    system: str,
    model: str = "qwen3:8b",
    timeout: int = 120,
    base_url: str = "http://localhost:11434",
) -> str:
    """Call Ollama local LLM.

    Args:
        prompt: User prompt text.
        system: System instruction text.
        model: Ollama model name.
        timeout: HTTP timeout in seconds.
        base_url: Ollama server URL.

    Returns:
        Raw response text from Ollama.

    Raises:
        RuntimeError: On connection error, timeout, or non-200 response.
    """
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "system": system,
        "format": "json",
        "stream": False,
        "keep_alive": "10m",
        "options": {"temperature": 0.3, "num_predict": 500},
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


def fallback_chain(prompt: str, system: str) -> tuple[str, str]:
    """Try LLM providers in order: Gemini CLI -> Gemini SDK -> Ollama.

    Args:
        prompt: User prompt text.
        system: System instruction text.

    Returns:
        Tuple of (response_text, provider_name).

    Raises:
        RuntimeError: If all 3 providers fail.
    """
    providers: list[tuple[str, object]] = [
        ("gemini_cli", call_gemini_cli),
        ("gemini_sdk", call_gemini_sdk),
        ("ollama", call_ollama),
    ]
    errors: list[str] = []
    for name, func in providers:
        try:
            result = func(prompt, system)  # type: ignore[operator]
            return (result, name)
        except Exception as e:
            logger.warning("LLM fallback: %s failed: %s", name, e)
            errors.append(f"{name}: {e}")

    raise RuntimeError(f"All LLM providers failed: {'; '.join(errors)}")
