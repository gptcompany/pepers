"""Prometheus metrics for the orchestrator pipeline.

Pipeline-specific counters, histograms, and gauges that track execution
of the 5-stage PePeRS pipeline (discovery -> analyzer -> extractor ->
validator -> codegen).

Counter names omit the ``_total`` suffix because prometheus-client
appends it automatically.
"""

from prometheus_client import Counter, Gauge, Histogram

PIPELINE_RUN_DURATION = Histogram(
    "pipeline_run_duration_seconds",
    "Total pipeline run duration in seconds",
    namespace="pepers",
    buckets=(10, 30, 60, 120, 300, 600, 900, 1200, 1800, 3600),
)

STAGE_DURATION = Histogram(
    "stage_duration_seconds",
    "Per-stage duration in seconds",
    ["stage"],
    namespace="pepers",
    buckets=(1, 5, 10, 30, 60, 120, 300, 600),
)

STAGE_COMPLETED = Counter(
    "stage_completed",
    "Pipeline stages completed",
    ["stage", "result"],
    namespace="pepers",
)

PIPELINE_RUNS_ACTIVE = Gauge(
    "pipeline_runs_active",
    "Currently active pipeline runs",
    namespace="pepers",
)

PAPERS_PROCESSED = Counter(
    "papers_processed",
    "Total papers processed through pipeline",
    namespace="pepers",
)

FORMULAS_VALIDATED = Counter(
    "formulas_validated",
    "Total formulas validated through pipeline",
    namespace="pepers",
)
