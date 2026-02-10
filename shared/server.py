"""Base HTTP server for research pipeline microservices.

Provides a base server and request handler that all services extend.
Improves on the CAS microservice pattern with:
- Simple route dispatch (decorator-based)
- JSON request/response helpers
- Structured error responses with proper status codes
- Python logging integration (for Loki/journald)
- Graceful SIGTERM handling
- Standard /health and /status endpoints built-in

Usage:
    from shared.server import BaseService, BaseHandler, route

    class MyHandler(BaseHandler):
        @route("POST", "/process")
        def handle_process(self, data: dict) -> dict:
            return {"result": "processed"}

    service = BaseService("my-service", port=8770, handler=MyHandler)
    service.run()

Design decisions:
- Route dispatch via method decorator (not monolithic do_POST/do_GET)
- JSON parsing/sending centralized in BaseHandler
- Error handling returns proper HTTP status codes (400, 404, 422, 500)
- SIGTERM handler for clean systemd stop
- Health/status endpoints auto-registered
"""

from __future__ import annotations

import json
import logging
import signal
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable


logger = logging.getLogger(__name__)


def route(method: str, path: str) -> Callable:
    """Decorator to register a route handler.

    Args:
        method: HTTP method (GET, POST).
        path: URL path to match.

    Returns:
        Decorated handler function.
    """
    ...


class BaseHandler(BaseHTTPRequestHandler):
    """Base request handler with JSON helpers and route dispatch.

    Subclass this and add @route-decorated methods for each endpoint.
    /health and /status are provided automatically.
    """

    def send_json(self, data: dict | list, status: int = 200) -> None:
        """Send a JSON response with proper headers.

        Args:
            data: Response body (will be JSON-serialized).
            status: HTTP status code.
        """
        ...

    def send_error_json(self, error: str, code: str, status: int = 400,
                        details: dict | None = None) -> None:
        """Send a standard error response.

        Format: {"error": "message", "code": "ERROR_CODE", "details": {}}

        Args:
            error: Human-readable error message.
            code: Machine-readable error code.
            status: HTTP status code.
            details: Optional additional error details.
        """
        ...

    def read_json(self) -> dict | None:
        """Read and parse JSON from request body.

        Returns:
            Parsed dict, or None if body is missing/invalid (error already sent).
        """
        ...


class BaseService:
    """Base microservice wrapping HTTPServer.

    Handles server lifecycle, SIGTERM, and logging setup.

    Args:
        name: Service name (used in logs and /health).
        port: TCP port to listen on.
        handler: BaseHandler subclass.
        db_path: Optional SQLite database path.
    """

    def __init__(self, name: str, port: int, handler: type[BaseHandler],
                 db_path: str | None = None) -> None:
        ...

    def run(self) -> None:
        """Start the HTTP server (blocking). Handles SIGTERM gracefully."""
        ...
