"""Unit tests for Prometheus metrics instrumentation in shared/server.py.

Tests the /metrics endpoint, request counting, duration histograms,
and error counting.  Each test class uses a unique handler subclass
and BaseService on its own port so label filtering keeps assertions
clean.  Metrics are global singletons — counters accumulate across
tests — so we use a before/after pattern instead of exact equality.
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest
from prometheus_client import REGISTRY

from shared.server import BaseHandler, BaseService, route


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _get_metrics_text(port: int) -> str:
    """Fetch /metrics endpoint and return decoded text."""
    resp = urllib.request.urlopen(f"http://localhost:{port}/metrics")
    return resp.read().decode()


def _sample_value(metric_name: str, labels: dict) -> float:
    """Read a metric value from the global REGISTRY."""
    val = REGISTRY.get_sample_value(metric_name, labels)
    return val if val is not None else 0.0


# ---- Test: /metrics endpoint format and content ----


class TestMetricsEndpoint:
    """Test that GET /metrics returns valid Prometheus text exposition."""

    @pytest.fixture(autouse=True)
    def setup_server(self):
        self.port = _get_free_port()

        class MetricsFormatHandler(BaseHandler):
            @route("GET", "/ping")
            def handle_ping(self):
                return {"pong": True}

        self.service = BaseService(
            "metrics-format-svc", self.port, MetricsFormatHandler
        )
        self.thread = threading.Thread(target=self.service.run, daemon=True)
        self.thread.start()
        time.sleep(0.3)
        yield
        if self.service.server:
            self.service.server.shutdown()

    def test_metrics_endpoint_returns_prometheus_format(self):
        resp = urllib.request.urlopen(f"http://localhost:{self.port}/metrics")
        content_type = resp.headers.get("Content-Type", "")
        assert content_type.startswith("text/plain"), f"Unexpected Content-Type: {content_type}"
        body = resp.read().decode()
        assert "# HELP" in body
        assert "# TYPE" in body

    def test_metrics_endpoint_contains_pepers_prefix(self):
        # Hit /ping first to populate metrics
        urllib.request.urlopen(f"http://localhost:{self.port}/ping")
        body = _get_metrics_text(self.port)
        assert "pepers_" in body


# ---- Test: Request counting ----


class TestRequestCount:
    """Test that pepers_request_count_total increments after requests."""

    @pytest.fixture(autouse=True)
    def setup_server(self):
        self.port = _get_free_port()

        class ReqCountHandler(BaseHandler):
            @route("POST", "/echo")
            def handle_echo(self, data):
                return {"echo": data}

        self.service = BaseService(
            "reqcount-svc", self.port, ReqCountHandler
        )
        self.thread = threading.Thread(target=self.service.run, daemon=True)
        self.thread.start()
        time.sleep(0.3)
        yield
        if self.service.server:
            self.service.server.shutdown()

    def test_request_count_increments(self):
        labels = {
            "service": "reqcount-svc",
            "endpoint": "/echo",
            "method": "POST",
            "status_code": "200",
        }
        before = _sample_value("pepers_request_count_total", labels)

        body = json.dumps({"hello": "world"}).encode()
        req = urllib.request.Request(
            f"http://localhost:{self.port}/echo",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req)

        after = _sample_value("pepers_request_count_total", labels)
        assert after == before + 1


# ---- Test: Duration histogram ----


class TestRequestDuration:
    """Test that pepers_request_duration_seconds records request latency."""

    @pytest.fixture(autouse=True)
    def setup_server(self):
        self.port = _get_free_port()

        class DurationHandler(BaseHandler):
            @route("GET", "/slow")
            def handle_slow(self):
                time.sleep(0.05)
                return {"ok": True}

        self.service = BaseService(
            "duration-svc", self.port, DurationHandler
        )
        self.thread = threading.Thread(target=self.service.run, daemon=True)
        self.thread.start()
        time.sleep(0.3)
        yield
        if self.service.server:
            self.service.server.shutdown()

    def test_request_duration_recorded(self):
        sum_labels = {
            "service": "duration-svc",
            "endpoint": "/slow",
            "method": "GET",
        }
        before_sum = _sample_value("pepers_request_duration_seconds_sum", sum_labels)

        urllib.request.urlopen(f"http://localhost:{self.port}/slow")

        after_sum = _sample_value("pepers_request_duration_seconds_sum", sum_labels)
        increment = after_sum - before_sum
        assert increment >= 0.05, f"Duration too low: {increment}"

        # Also check that bucket lines appear in the text output
        body = _get_metrics_text(self.port)
        assert "pepers_request_duration_seconds_bucket" in body


# ---- Test: Error counting ----


class TestErrorCount:
    """Test that pepers_error_count_total increments on 4xx/5xx."""

    @pytest.fixture(autouse=True)
    def setup_server(self):
        self.port = _get_free_port()

        class ErrorHandler(BaseHandler):
            @route("GET", "/fail")
            def handle_fail(self):
                raise RuntimeError("intentional error")

        self.service = BaseService(
            "error-svc", self.port, ErrorHandler
        )
        self.thread = threading.Thread(target=self.service.run, daemon=True)
        self.thread.start()
        time.sleep(0.3)
        yield
        if self.service.server:
            self.service.server.shutdown()

    def test_error_count_increments_on_500(self):
        labels_500 = {
            "service": "error-svc",
            "endpoint": "/fail",
            "method": "GET",
            "status_code": "500",
        }
        before = _sample_value("pepers_error_count_total", labels_500)

        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(f"http://localhost:{self.port}/fail")
        assert exc_info.value.code == 500

        after = _sample_value("pepers_error_count_total", labels_500)
        assert after == before + 1

    def test_error_count_increments_on_404(self):
        labels_404 = {
            "service": "error-svc",
            "endpoint": "/nonexistent",
            "method": "GET",
            "status_code": "404",
        }
        before = _sample_value("pepers_error_count_total", labels_404)

        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(f"http://localhost:{self.port}/nonexistent")
        assert exc_info.value.code == 404

        # Allow server thread to finish metrics bookkeeping under load
        time.sleep(0.1)
        after = _sample_value("pepers_error_count_total", labels_404)
        assert after == before + 1


# ---- Test: /metrics and /health excluded from counting ----


class TestExcludedEndpoints:
    """Test that /metrics and /health are excluded from request counting."""

    @pytest.fixture(autouse=True)
    def setup_server(self):
        self.port = _get_free_port()

        class ExcludeHandler(BaseHandler):
            pass

        self.service = BaseService(
            "exclude-svc", self.port, ExcludeHandler
        )
        self.thread = threading.Thread(target=self.service.run, daemon=True)
        self.thread.start()
        time.sleep(0.3)
        yield
        if self.service.server:
            self.service.server.shutdown()

    def test_metrics_endpoint_not_counted(self):
        labels = {
            "service": "exclude-svc",
            "endpoint": "/metrics",
            "method": "GET",
            "status_code": "200",
        }
        before = _sample_value("pepers_request_count_total", labels)

        # Hit /metrics several times
        for _ in range(3):
            urllib.request.urlopen(f"http://localhost:{self.port}/metrics")

        after = _sample_value("pepers_request_count_total", labels)
        assert after == before, (
            f"Expected no increment for /metrics, got {after - before}"
        )

    def test_health_endpoint_not_counted(self):
        labels = {
            "service": "exclude-svc",
            "endpoint": "/health",
            "method": "GET",
            "status_code": "200",
        }
        before = _sample_value("pepers_request_count_total", labels)

        urllib.request.urlopen(f"http://localhost:{self.port}/health")

        after = _sample_value("pepers_request_count_total", labels)
        assert after == before, (
            f"Expected no increment for /health, got {after - before}"
        )
