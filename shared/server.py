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
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable


logger = logging.getLogger(__name__)


class JsonFormatter(logging.Formatter):
    """JSON log formatter for Loki/journald structured logging."""

    def __init__(self, service: str = "unknown") -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "service": self.service,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)


def route(method: str, path: str) -> Callable:
    """Decorator to register a route handler.

    Args:
        method: HTTP method (GET, POST).
        path: URL path to match.

    Returns:
        Decorated handler function.
    """
    def decorator(fn: Callable) -> Callable:
        fn._route = (method.upper(), path)  # type: ignore[attr-defined]
        return fn
    return decorator


class BaseHandler(BaseHTTPRequestHandler):
    """Base request handler with JSON helpers and route dispatch.

    Subclass this and add @route-decorated methods for each endpoint.
    /health and /status are provided automatically.
    """

    # Class-level attributes set by BaseService
    service_name: str = "unknown"
    service_version: str = "0.1.0"
    service_start_time: float = 0.0
    db_path: str | None = None

    # Route registry, built lazily on first request
    _routes: dict[tuple[str, str], str] | None = None

    @classmethod
    def _build_routes(cls) -> dict[tuple[str, str], str]:
        """Scan class methods for @route decorators."""
        routes: dict[tuple[str, str], str] = {}
        for name in dir(cls):
            method = getattr(cls, name, None)
            if callable(method) and hasattr(method, "_route"):
                routes[method._route] = name  # type: ignore[attr-defined]
        return routes

    def _dispatch(self, http_method: str) -> None:
        """Dispatch request to matching route handler."""
        if self.__class__._routes is None:
            self.__class__._routes = self._build_routes()

        routes = self.__class__._routes
        path_no_query = self.path.split("?")[0]
        key = (http_method, path_no_query)
        handler_name = routes.get(key)

        if handler_name:
            handler = getattr(self, handler_name)
            try:
                if http_method == "POST":
                    data = self.read_json()
                    if data is None:
                        return  # error already sent by read_json
                    result = handler(data)
                else:
                    result = handler()
                if result is not None:
                    self.send_json(result)
            except BrokenPipeError:
                logger.warning("Client disconnected before response sent")
            except Exception as e:
                logger.exception("Handler error: %s", e)
                try:
                    self.send_error_json(str(e), "INTERNAL_ERROR", 500)
                except BrokenPipeError:
                    logger.warning("Client disconnected during error response")
        else:
            self.send_error_json(
                f"Not found: {self.path}", "NOT_FOUND", 404
            )

    def do_GET(self) -> None:
        """Handle GET requests via route dispatch."""
        self._dispatch("GET")

    def do_POST(self) -> None:
        """Handle POST requests via route dispatch."""
        self._dispatch("POST")

    def send_json(self, data: dict | list, status: int = 200) -> None:
        """Send a JSON response with proper headers.

        Args:
            data: Response body (will be JSON-serialized).
            status: HTTP status code.
        """
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
        response: dict[str, Any] = {"error": error, "code": code}
        if details:
            response["details"] = details
        self.send_json(response, status)

    def read_json(self) -> dict | None:
        """Read and parse JSON from request body.

        Returns:
            Parsed dict, or None if body is missing/invalid (error already sent).
        """
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self.send_error_json("Request body is empty", "INVALID_JSON", 400)
            return None
        try:
            body = self.rfile.read(content_length)
            return json.loads(body)
        except (json.JSONDecodeError, ValueError) as e:
            self.send_error_json(f"Invalid JSON: {e}", "INVALID_JSON", 400)
            return None

    def log_message(self, format: str, *args: Any) -> None:
        """Override default log to use Python logging instead of stderr."""
        logger.info("%s %s", self.client_address[0], format % args)


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
        self.name = name
        self.port = port
        self.handler = handler
        self.db_path = db_path
        self.server: HTTPServer | None = None
        self._start_time = time.time()

        # Inject service metadata into handler class
        handler.service_name = name
        handler.service_version = "0.1.0"
        handler.service_start_time = self._start_time
        handler.db_path = db_path

        # Register built-in endpoints
        self._register_builtins(handler)

    def _register_builtins(self, handler: type[BaseHandler]) -> None:
        """Register /health and /status as built-in routes."""

        @route("GET", "/health")
        def handle_health(self_handler: BaseHandler) -> dict:
            return {
                "status": "ok",
                "service": handler.service_name,
                "uptime_seconds": round(
                    time.time() - handler.service_start_time, 1
                ),
            }

        @route("GET", "/status")
        def handle_status(self_handler: BaseHandler) -> dict:
            result: dict[str, Any] = {
                "service": handler.service_name,
                "version": handler.service_version,
                "uptime_seconds": round(
                    time.time() - handler.service_start_time, 1
                ),
            }
            if handler.db_path:
                result["db_path"] = handler.db_path
            return result

        # Bind to handler class only if not already defined by subclass
        if not hasattr(handler, "handle_health") or not hasattr(
            getattr(handler, "handle_health", None), "_route"
        ):
            handler.handle_health = handle_health  # type: ignore[attr-defined]
        if not hasattr(handler, "handle_status") or not hasattr(
            getattr(handler, "handle_status", None), "_route"
        ):
            handler.handle_status = handle_status  # type: ignore[attr-defined]

        # Reset route cache so new routes are discovered
        handler._routes = None

    def _setup_logging(self) -> None:
        """Configure JSON structured logging for Loki/journald."""
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        root.handlers.clear()
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter(service=self.name))
        root.addHandler(handler)

    def _handle_sigterm(self, signum: int, frame: Any) -> None:
        """Handle SIGTERM for graceful shutdown."""
        logger.info("SIGTERM received, shutting down...")
        if self.server:
            self.server.shutdown()

    def run(self) -> None:
        """Start the HTTP server (blocking). Handles SIGTERM gracefully."""
        self._setup_logging()
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGTERM, self._handle_sigterm)

        self.server = HTTPServer(("0.0.0.0", self.port), self.handler)
        logger.info("Starting %s on port %d", self.name, self.port)

        try:
            self.server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            if self.server:
                self.server.server_close()
            logger.info("%s stopped", self.name)
