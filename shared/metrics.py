"""Shared Prometheus metrics for all PePeRS HTTP microservices.

Defines module-level metric singletons imported by shared/server.py.
All metric names use the ``pepers`` namespace prefix so they are
easily filterable in Prometheus / Grafana.

Counter names omit the ``_total`` suffix because prometheus-client
appends it automatically.
"""

from prometheus_client import Counter, Histogram

REQUEST_COUNT = Counter(
    "request_count",
    "Total HTTP requests",
    ["service", "endpoint", "method", "status_code"],
    namespace="pepers",
)

REQUEST_DURATION = Histogram(
    "request_duration_seconds",
    "HTTP request duration in seconds",
    ["service", "endpoint", "method"],
    namespace="pepers",
)

ERROR_COUNT = Counter(
    "error_count",
    "Total HTTP error responses (4xx/5xx)",
    ["service", "endpoint", "method", "status_code"],
    namespace="pepers",
)
