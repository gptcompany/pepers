"""Step: verify external services (CAS, RAG, Ollama)."""

from __future__ import annotations

import os

import requests
from rich.console import Console

_EXTERNAL_SERVICES = [
    {
        "name": "CAS Service",
        "env_urls": ["RP_VALIDATOR_CAS_URL", "RP_CAS_URL"],
        "default_url": "http://localhost:8769",
        "health_path": "/health",
        "setup_hint": (
            "Install & run CAS Service:\n"
            "  cd /path/to/cas-service && cas-setup\n"
            "  Or: uv run python -m cas_service.main"
        ),
    },
    {
        "name": "RAG Service",
        "env_urls": ["RP_EXTRACTOR_RAG_URL", "RP_RAG_QUERY_URL", "RP_RAG_URL"],
        "default_url": "http://localhost:8767",
        "health_path": "/health",
        "setup_hint": (
            "Install & run RAG Service:\n"
            "  cd /path/to/rag-service && rag-setup\n"
            "  Or: ./scripts/raganything_start.sh"
        ),
    },
    {
        "name": "Ollama",
        "env_urls": ["RP_CODEGEN_OLLAMA_URL", "RP_OLLAMA_URL"],
        "default_url": "http://localhost:11434",
        "health_path": "/",
        "setup_hint": (
            "Install Ollama:\n"
            "  curl -fsSL https://ollama.ai/install.sh | sh\n"
            "  ollama serve"
        ),
    },
]


class ExternalServiceCheck:
    """Check a single external service."""

    def __init__(self, svc: dict) -> None:
        self._svc = svc
        self.name = svc["name"]

    def _url(self) -> str:
        env_urls = self._svc.get("env_urls")
        if isinstance(env_urls, list):
            for key in env_urls:
                val = os.environ.get(key, "").strip()
                if val:
                    return val
        env_url = self._svc.get("env_url")
        if isinstance(env_url, str):
            val = os.environ.get(env_url, "").strip()
            if val:
                return val
        return self._svc["default_url"]

    def check(self) -> bool:
        url = self._url().rstrip("/") + self._svc["health_path"]
        try:
            resp = requests.get(url, timeout=5)
            return resp.status_code < 500
        except (requests.ConnectionError, requests.Timeout):
            return False

    def install(self, console: Console) -> bool:
        console.print(f"[yellow]{self.name} is not reachable at {self._url()}[/]")
        console.print(f"[dim]{self._svc['setup_hint']}[/]")
        return False  # can't auto-install external services

    def verify(self) -> bool:
        return self.check()


def get_all_steps() -> list:
    return [ExternalServiceCheck(svc) for svc in _EXTERNAL_SERVICES]
