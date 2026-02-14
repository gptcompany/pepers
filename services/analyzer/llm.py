"""LLM client functions for the Analyzer service.

Re-exports from shared.llm for backward compatibility.
All LLM client logic lives in shared/llm.py since Phase 18.

Stdlib modules imported here for mock.patch backward compatibility
(tests mock services.analyzer.llm.subprocess, etc.).
"""

import subprocess  # noqa: F401
import urllib.request  # noqa: F401

from shared.llm import (  # noqa: F401
    _get_gemini_api_key,
    _strip_markdown_fences,
    call_gemini_cli,
    call_gemini_sdk,
    call_ollama,
    fallback_chain,
)
