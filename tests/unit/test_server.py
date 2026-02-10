"""Unit tests for shared/server.py — HTTP server, routing, JSON helpers."""

from __future__ import annotations

import json
import logging
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

from shared.server import BaseHandler, BaseService, JsonFormatter, route


def _get_free_port():
    """Get a free TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class TestJsonFormatter:
    """Tests for JsonFormatter."""

    def test_basic_format(self):
        fmt = JsonFormatter(service="test-svc")
        record = logging.LogRecord("test", logging.INFO, "", 0, "hello", (), None)
        output = json.loads(fmt.format(record))
        assert output["service"] == "test-svc"
        assert output["msg"] == "hello"
        assert output["level"] == "INFO"
        assert "timestamp" in output

    def test_with_exception(self):
        fmt = JsonFormatter(service="test-svc")
        try:
            raise ValueError("test error")
        except ValueError:
            exc_info = sys.exc_info()
        record = logging.LogRecord(
            "test", logging.ERROR, "", 0, "failed", (), exc_info
        )
        output = json.loads(fmt.format(record))
        assert "exception" in output
        assert "ValueError" in output["exception"]

    def test_default_service(self):
        fmt = JsonFormatter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        output = json.loads(fmt.format(record))
        assert output["service"] == "unknown"

    def test_output_is_valid_json(self):
        fmt = JsonFormatter(service="test")
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "multiline\nmessage", (), None
        )
        output = fmt.format(record)
        parsed = json.loads(output)
        assert parsed["msg"] == "multiline\nmessage"


class TestRouteDecorator:
    """Tests for route() decorator."""

    def test_sets_route_attribute(self):
        @route("GET", "/test")
        def handler(self):
            pass

        assert handler._route == ("GET", "/test")  # type: ignore[attr-defined]

    def test_uppercases_method(self):
        @route("post", "/submit")
        def handler(self, data):
            pass

        assert handler._route == ("POST", "/submit")  # type: ignore[attr-defined]

    def test_preserves_function(self):
        @route("GET", "/test")
        def handler(self):
            return {"ok": True}

        assert handler(None) == {"ok": True}


class TestBaseHandlerRouting:
    """Tests for BaseHandler route building."""

    def test_build_routes_discovers_decorated_methods(self):
        class TestHandler(BaseHandler):
            @route("GET", "/ping")
            def handle_ping(self):
                return {"pong": True}

            @route("POST", "/echo")
            def handle_echo(self, data):
                return data

        TestHandler._routes = None
        routes = TestHandler._build_routes()
        assert ("GET", "/ping") in routes
        assert ("POST", "/echo") in routes
        assert routes[("GET", "/ping")] == "handle_ping"

    def test_build_routes_ignores_non_decorated(self):
        class TestHandler(BaseHandler):
            def not_a_route(self):
                pass

            @route("GET", "/only")
            def handle_only(self):
                return {}

        TestHandler._routes = None
        routes = TestHandler._build_routes()
        assert ("GET", "/only") in routes
        assert len([v for v in routes.values() if v == "not_a_route"]) == 0


class TestBaseServiceAndHTTP:
    """Tests for BaseService with real HTTP requests."""

    @pytest.fixture(autouse=True)
    def setup_server(self):
        self.port = _get_free_port()

        class TestHandler(BaseHandler):
            @route("GET", "/ping")
            def handle_ping(self):
                return {"pong": True}

            @route("POST", "/echo")
            def handle_echo(self, data):
                return {"echo": data}

            @route("GET", "/error")
            def handle_error(self):
                raise RuntimeError("intentional error")

            @route("POST", "/validate")
            def handle_validate(self, data):
                if "name" not in data:
                    self.send_error_json(
                        "name required", "MISSING_FIELD", 422, {"field": "name"}
                    )
                    return None
                return {"valid": True}

        self.service = BaseService(
            "test-svc", self.port, TestHandler, db_path="/tmp/test.db"
        )
        self.thread = threading.Thread(target=self.service.run, daemon=True)
        self.thread.start()
        time.sleep(0.3)
        yield
        if self.service.server:
            self.service.server.shutdown()

    def _url(self, path):
        return f"http://localhost:{self.port}{path}"

    def _get(self, path):
        resp = urllib.request.urlopen(self._url(path))
        return json.loads(resp.read())

    def _post(self, path, data):
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            self._url(path),
            data=body,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req)
        return json.loads(resp.read())

    def test_health_endpoint(self):
        data = self._get("/health")
        assert data["status"] == "ok"
        assert data["service"] == "test-svc"
        assert "uptime_seconds" in data

    def test_status_endpoint(self):
        data = self._get("/status")
        assert data["service"] == "test-svc"
        assert data["version"] == "0.1.0"
        assert data["db_path"] == "/tmp/test.db"

    def test_status_without_db_path(self):
        port2 = _get_free_port()

        class MinimalHandler(BaseHandler):
            pass

        svc2 = BaseService("no-db", port2, MinimalHandler)
        t = threading.Thread(target=svc2.run, daemon=True)
        t.start()
        time.sleep(0.3)
        try:
            resp = urllib.request.urlopen(f"http://localhost:{port2}/status")
            data = json.loads(resp.read())
            assert "db_path" not in data
        finally:
            if svc2.server:
                svc2.server.shutdown()

    def test_custom_get_route(self):
        data = self._get("/ping")
        assert data["pong"] is True

    def test_custom_post_route(self):
        data = self._post("/echo", {"hello": "world"})
        assert data["echo"]["hello"] == "world"

    def test_404_for_unknown_path(self):
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(self._url("/nonexistent"))
        assert exc_info.value.code == 404
        data = json.loads(exc_info.value.read())
        assert data["code"] == "NOT_FOUND"

    def test_handler_exception_returns_500(self):
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(self._url("/error"))
        assert exc_info.value.code == 500
        data = json.loads(exc_info.value.read())
        assert data["code"] == "INTERNAL_ERROR"

    def test_invalid_json_post(self):
        req = urllib.request.Request(
            self._url("/echo"),
            data=b"not json",
            headers={"Content-Type": "application/json", "Content-Length": "8"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req)
        assert exc_info.value.code == 400
        data = json.loads(exc_info.value.read())
        assert data["code"] == "INVALID_JSON"

    def test_empty_body_post(self):
        req = urllib.request.Request(
            self._url("/echo"),
            data=b"",
            headers={"Content-Type": "application/json", "Content-Length": "0"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req)
        assert exc_info.value.code == 400

    def test_error_with_details(self):
        data = json.dumps({}).encode()
        req = urllib.request.Request(
            self._url("/validate"),
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req)
        assert exc_info.value.code == 422
        resp = json.loads(exc_info.value.read())
        assert resp["code"] == "MISSING_FIELD"
        assert resp["details"]["field"] == "name"

    def test_query_string_stripped(self):
        data = self._get("/ping?foo=bar")
        assert data["pong"] is True

    def test_service_injects_metadata(self):
        class CheckHandler(BaseHandler):
            pass

        port = _get_free_port()
        BaseService("injected-name", port, CheckHandler)
        assert CheckHandler.service_name == "injected-name"
        assert CheckHandler.service_version == "0.1.0"
