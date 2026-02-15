"""HTTP client for the CAS microservice.

Uses urllib.request (stdlib) — no external dependencies.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class EngineResult:
    """Result from a single CAS engine (mirrors CAS service response)."""

    engine: str
    success: bool
    is_valid: bool | None = None
    simplified: str | None = None
    original_parsed: str | None = None
    error: str | None = None
    time_ms: int = 0


@dataclass
class CASResponse:
    """Full response from CAS service /validate endpoint."""

    results: list[EngineResult]
    latex_preprocessed: str
    time_ms: int


class CASServiceError(Exception):
    """Raised when CAS service is unreachable or returns an error."""

    pass


class CASClient:
    """HTTP client for the CAS microservice."""

    def __init__(self, base_url: str = "http://localhost:8769",
                 timeout: int = 120) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def validate(self, latex: str,
                 engines: list[str] | None = None) -> CASResponse:
        """Send a formula to the CAS service for validation."""
        payload: dict = {"latex": latex}
        if engines:
            payload["engines"] = engines

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/validate",
            data=data,
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            try:
                error_body = json.loads(e.read())
                msg = error_body.get("error", "unknown")
            except Exception:
                msg = str(e)
            raise CASServiceError(f"CAS error {e.code}: {msg}") from e
        except urllib.error.URLError as e:
            raise CASServiceError(f"CAS service unreachable: {e}") from e

        results = [
            EngineResult(
                engine=r["engine"],
                success=r["success"],
                is_valid=r.get("is_valid"),
                simplified=r.get("simplified"),
                original_parsed=r.get("original_parsed"),
                error=r.get("error"),
                time_ms=r.get("time_ms", 0),
            )
            for r in body["results"]
        ]

        return CASResponse(
            results=results,
            latex_preprocessed=body["latex_preprocessed"],
            time_ms=body["time_ms"],
        )

    def health(self) -> bool:
        """Check if CAS service is healthy."""
        try:
            req = urllib.request.Request(f"{self.base_url}/health")
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = json.loads(resp.read())
                return body.get("status") == "ok"
        except Exception:
            return False
