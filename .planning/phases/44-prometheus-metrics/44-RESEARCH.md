# Phase 44: Prometheus Metrics - Research

**Researched:** 2026-02-21
**Domain:** Prometheus instrumentation for Python HTTP microservices
**Confidence:** HIGH

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Label Granularity
- Labels per metrica HTTP: `service`, `endpoint`, `method`, `status_code`
- `service` = nome logico (discovery, analyzer, extractor, validator, codegen, orchestrator) -- non porta
- `endpoint` = path HTTP completo (es. `/discover`, `/analyze`, `/metrics`). Tutti gli endpoint PePeRS sono statici (nessun parametro dinamico nel path), quindi nessun rischio di cardinalita' esplosiva
- Namespace prefix: `pepers_` su tutte le metriche (es. `pepers_request_count`, `pepers_request_duration_seconds`)

#### Pipeline Stage Breakdown
- Orchestrator espone metriche per-stage oltre ai totali pipeline
- `pepers_stage_duration_seconds{stage="discovery"}` histogram per ogni stage
- `pepers_stage_completed_total{stage="validator", result="success|failure|skipped"}` counter con label result
- `pepers_pipeline_runs_active` gauge per pipeline run attivi in tempo reale
- Stages: discovery, analyzer, extractor, validator, codegen

#### Histogram Buckets
- Request HTTP (singoli servizi): default prometheus-client (0.005 - 10s)
- Pipeline run duration: custom buckets (10, 30, 60, 120, 300, 600, 900, 1200, 1800, 3600s)
- Stage duration: custom buckets (1, 5, 10, 30, 60, 120, 300, 600s)

### Claude's Discretion
- Error classification approach (per-type labels vs contatore unico vs status-code-only)
- LLM fallback tracking (valutare se rientra in scope o se rimandare a MONX-01)
- CAS error counter separato vs catturato in stage result
- Counter dedicato per 413 rejected vs catturato in request_count con status_code=413
- Formulas-per-paper histogram vs solo totale
- Scelta dei bucket per stage_duration_seconds

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope

</user_constraints>

<phase_requirements>

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| MON-01 | Each service exposes /metrics endpoint with Prometheus format (request count, duration histogram, error count) | prometheus-client library provides Counter, Histogram, generate_latest(); integration point is shared/server.py BaseHandler._dispatch() for automatic request tracking; GET /metrics route in BaseService._register_builtins() |
| MON-02 | Orchestrator exposes pipeline-specific metrics (papers processed, formulas validated, run duration) | Histogram with custom buckets for pipeline_run_duration_seconds; Counter for papers_processed_total and formulas_validated_total; Gauge for pipeline_runs_active; instrumentation points in services/orchestrator/pipeline.py PipelineRunner.run() |

</phase_requirements>

## Summary

This phase adds Prometheus metrics instrumentation to 7 PePeRS HTTP microservices (discovery:8770, analyzer:8771, extractor:8772, validator:8773, codegen:8774, orchestrator:8775, mcp:8776). The `prometheus-client` library (v0.24.1) is the only new dependency. It is thread-safe, lightweight (~60KB), and provides Counter, Histogram, Gauge metric types plus `generate_latest()` to serialize metrics in Prometheus text format.

The architecture centers on **shared/server.py** as the single instrumentation point. The `_dispatch()` method in `BaseHandler` already handles all routing -- wrapping it with timing and counting gives automatic request metrics for every service. A new `GET /metrics` built-in route (like the existing `/health` and `/status`) calls `generate_latest()` and returns Prometheus text format. The orchestrator's `pipeline.py` module additionally instruments per-stage timing and pipeline-level counters.

**Important architectural note:** The MCP service (port 8776) uses FastMCP SDK, NOT shared/server.py. It cannot share the same metrics middleware. Since the MCP server is a thin proxy to the orchestrator, it has minimal standalone metrics value. If metrics on MCP are required, they would need separate instrumentation via a custom FastMCP middleware or a dedicated Prometheus HTTP server on a different port. **Recommendation:** Skip MCP metrics for this phase -- the orchestrator already captures the underlying work.

**Primary recommendation:** Instrument shared/server.py._dispatch() with request Counter + Histogram, add GET /metrics to BaseService._register_builtins(), add pipeline metrics to PipelineRunner.run(). One file for shared metrics module, two files modified (server.py, pipeline.py).

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| prometheus-client | 0.24.1 | Metrics collection and exposition | Official Prometheus Python client. Thread-safe. Used by >90% of Python Prometheus deployments |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| (none) | -- | -- | prometheus-client is self-contained |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| prometheus-client | opentelemetry-api + OTLP exporter | Heavier (50+ deps), overkill for Prometheus-only scraping, YAGNI |
| prometheus-client | Custom text format generator | Error-prone, misses histogram quantile math, counter _total suffix conventions |

**Installation:**
```bash
uv add prometheus-client
```

## Architecture Patterns

### Recommended Module Structure
```
shared/
  server.py          # Modified: wrap _dispatch(), add /metrics route
  metrics.py         # NEW: metric definitions (Counter, Histogram, Gauge)
services/
  orchestrator/
    pipeline.py      # Modified: instrument run(), per-stage timing
    metrics.py       # NEW: orchestrator-specific metric definitions
```

### Pattern 1: Centralized Metric Definitions (Module-Level Singletons)
**What:** Define all metrics as module-level objects in dedicated `metrics.py` files. Import where needed.
**When to use:** Always. prometheus-client metrics are global singletons registered to the default REGISTRY. Creating the same metric name twice raises a ValueError.
**Example:**
```python
# shared/metrics.py
# Source: https://prometheus.github.io/client_python
from prometheus_client import Counter, Histogram, Gauge

# -- HTTP Request Metrics (all services) --
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
```

### Pattern 2: Middleware-Style Instrumentation in _dispatch()
**What:** Wrap the existing _dispatch() method to automatically record metrics for every request.
**When to use:** For HTTP request metrics. Avoids touching individual service handlers.
**Example:**
```python
# In shared/server.py BaseHandler._dispatch()
import time
from shared.metrics import REQUEST_COUNT, REQUEST_DURATION, ERROR_COUNT

def _dispatch(self, http_method: str) -> None:
    start_time = time.monotonic()
    # ... existing route resolution ...

    # After handler completes:
    duration = time.monotonic() - start_time
    service = self.__class__.service_name
    endpoint = path_no_query
    status = "200"  # or actual status code

    REQUEST_COUNT.labels(
        service=service, endpoint=endpoint,
        method=http_method, status_code=status,
    ).inc()
    REQUEST_DURATION.labels(
        service=service, endpoint=endpoint, method=http_method,
    ).observe(duration)
```

### Pattern 3: Built-in /metrics Endpoint via BaseService
**What:** Register GET /metrics in _register_builtins() alongside /health and /status.
**When to use:** Always. Every service automatically gets /metrics without code changes.
**Example:**
```python
# In shared/server.py BaseService._register_builtins()
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

@route("GET", "/metrics")
def handle_metrics(self_handler: BaseHandler) -> None:
    """Expose Prometheus metrics."""
    output = generate_latest()
    self_handler.send_response(200)
    self_handler.send_header("Content-Type", CONTENT_TYPE_LATEST)
    self_handler.send_header("Content-Length", str(len(output)))
    self_handler.end_headers()
    self_handler.wfile.write(output)
```

**IMPORTANT:** The /metrics handler must NOT return a dict (which would go through send_json). It must write raw bytes with `Content-Type: text/plain; version=1.0.0; charset=utf-8`. The handler should send the response directly and return None.

### Pattern 4: Pipeline Metrics in Orchestrator
**What:** Orchestrator-specific metrics for pipeline runs and per-stage timing.
**When to use:** Only in orchestrator service.
**Example:**
```python
# services/orchestrator/metrics.py
from prometheus_client import Counter, Histogram, Gauge

PIPELINE_RUN_DURATION = Histogram(
    "pipeline_run_duration_seconds",
    "Total pipeline run duration",
    namespace="pepers",
    buckets=(10, 30, 60, 120, 300, 600, 900, 1200, 1800, 3600),
)

STAGE_DURATION = Histogram(
    "stage_duration_seconds",
    "Per-stage duration",
    ["stage"],
    namespace="pepers",
    buckets=(1, 5, 10, 30, 60, 120, 300, 600),
)

STAGE_COMPLETED = Counter(
    "stage_completed_total",
    "Stages completed",
    ["stage", "result"],
    namespace="pepers",
)

PIPELINE_RUNS_ACTIVE = Gauge(
    "pipeline_runs_active",
    "Currently active pipeline runs",
    namespace="pepers",
)

PAPERS_PROCESSED = Counter(
    "papers_processed_total",
    "Total papers processed through pipeline",
    namespace="pepers",
)

FORMULAS_VALIDATED = Counter(
    "formulas_validated_total",
    "Total formulas validated",
    namespace="pepers",
)
```

### Anti-Patterns to Avoid
- **Creating metrics inside request handlers:** Metrics must be module-level singletons. Creating them per-request causes `ValueError: Duplicated timeseries`.
- **Using paper_id or formula_id as labels:** Causes cardinality explosion. These are already a locked decision (never use as labels).
- **Returning dict from /metrics handler:** Prometheus expects `text/plain` not `application/json`. The handler must bypass send_json() and write raw bytes.
- **Separate generate_latest per service:** All metrics share the global REGISTRY. One generate_latest() call returns ALL metrics, which is the correct behavior -- each service process has its own REGISTRY.
- **Starting a separate HTTP server for metrics:** prometheus-client offers `start_http_server()`, but PePeRS already has HTTP servers. Use the existing server, add a /metrics route.

## Claude's Discretion Recommendations

### Error Classification: Use status-code-only approach
**Recommendation:** Capture errors purely via the `status_code` label on `pepers_request_count` and a separate `pepers_error_count` counter also using `status_code`. This means:
- `pepers_request_count{status_code="413"}` captures 413 rejections
- `pepers_error_count{status_code="500"}` captures 500 errors
- No separate per-type error labels (VALIDATION_ERROR, INTERNAL_ERROR, etc.)

**Rationale:** The status code is already in the label. Adding error-type labels would increase cardinality without meaningful benefit for alerting. Grafana dashboards can group by status_code ranges (4xx vs 5xx). The error code detail is in the logs (structured JSON via Loki).

### LLM Fallback Tracking: Defer to Phase 46/MONX-01
**Recommendation:** Out of scope for Phase 44. LLM fallback chains are internal to individual services (analyzer, codegen). Tracking which LLM provider was used requires per-handler instrumentation, not middleware-level. This is better addressed as a service-specific enhancement.

### CAS Error Counter: Captured in stage result
**Recommendation:** CAS errors are already captured via `pepers_stage_completed_total{stage="validator", result="failure"}`. No separate CAS error counter needed. If CAS-specific tracking is needed later, it's a validator service enhancement, not a shared metrics concern.

### 413 Rejection Counter: Captured in request_count
**Recommendation:** `pepers_request_count{status_code="413"}` already captures this. A dedicated counter would be redundant. Use PromQL `sum(pepers_request_count{status_code="413"})` for dashboards.

### Formulas-per-paper Histogram: Skip, use totals only
**Recommendation:** Skip. The `pepers_formulas_validated_total` counter provides the total. Per-paper distribution is better queried from the database. Adding a histogram per-paper would require the orchestrator to track paper-level formula counts, adding complexity for marginal monitoring value.

### Stage Duration Buckets: Use the locked decision as-is
**Recommendation:** The user-decided buckets (1, 5, 10, 30, 60, 120, 300, 600s) provide good coverage for stages ranging from discovery (~5-30s) to codegen (~30-300s). No changes needed.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Prometheus text format | Custom string builder for `# HELP`, `# TYPE`, metric lines | `generate_latest()` from prometheus-client | Format has subtle rules: counter _total suffix, histogram _bucket/_sum/_count, escaping, timestamp handling |
| Thread-safe counters | `threading.Lock` + dict-based counters | `Counter` / `Histogram` / `Gauge` from prometheus-client | Built-in lock management, label handling, correct atomic increments |
| Histogram bucket math | Manual bucket boundary tracking | `Histogram(buckets=(...))` | Automatic `_le` boundary tracking, `_sum` and `_count` aggregation |
| Metric registry | Global dict of metrics | `REGISTRY` (default CollectorRegistry) | Handles metric registration, deduplication, collection lifecycle |

**Key insight:** The prometheus-client library handles text format serialization, thread-safe metric updates, histogram bucket math, and the global registry. Any hand-rolled solution would miss edge cases (e.g., histogram _created timestamps, counter _total suffix conventions, label escaping).

## Common Pitfalls

### Pitfall 1: Metric Duplication on Module Reload
**What goes wrong:** Creating metrics at module level works fine in production, but test code that imports the metrics module multiple times (or re-imports after patching) triggers `ValueError: Duplicated timeseries in CollectorRegistry`.
**Why it happens:** prometheus-client's default REGISTRY is global per-process. Re-importing the module tries to re-register the same metric names.
**How to avoid:** In tests, either (a) import metrics once at module level, (b) use a custom CollectorRegistry per test, or (c) call `REGISTRY.unregister()` in teardown. Option (a) is simplest.
**Warning signs:** Tests fail with `ValueError: Duplicated timeseries` when run in sequence.

### Pitfall 2: /metrics Handler Returns JSON
**What goes wrong:** If the /metrics handler returns a dict, `_dispatch()` will call `send_json()`, wrapping the Prometheus text format in JSON with `Content-Type: application/json`. Prometheus scraper will reject it.
**Why it happens:** PePeRS convention is that route handlers return dict -> auto-serialized by send_json(). But /metrics needs raw bytes with text/plain content type.
**How to avoid:** The /metrics handler must call `send_response()` + `send_header()` + `wfile.write()` directly and return None.
**Warning signs:** Prometheus scraper logs "unexpected content type" or "invalid exposition format".

### Pitfall 3: Tracking Status Code Requires Refactoring _dispatch()
**What goes wrong:** The current `_dispatch()` method doesn't track the HTTP status code of responses. The status code is only set inside `send_json()` and `send_error_json()`. The middleware wrapper needs to know the status code to populate the `status_code` label.
**Why it happens:** The response status is set deep inside `send_json()` / `send_error_json()`, not returned to `_dispatch()`.
**How to avoid:** Two approaches:
  1. **Instance variable approach:** Set `self._response_status = 200` in _dispatch() before calling handler, then override it in `send_json()` and `send_error_json()`. Read it after handler returns.
  2. **Wrapper approach:** Monkey-patch `send_response()` to capture the status code.
  Option 1 is simpler and matches the existing pattern (e.g., `self.last_request_time`).
**Warning signs:** All requests show status_code="200" even for errors.

### Pitfall 4: Observing Duration for Errored Requests
**What goes wrong:** If the handler raises an exception, the timing observation is skipped (code after handler call doesn't execute).
**Why it happens:** Exception flow bypasses the post-handler metrics code.
**How to avoid:** Use try/finally to ensure duration is always observed, even on error. The status_code label should reflect the error status (500).
**Warning signs:** Duration histogram only shows successful requests; error requests have no timing data.

### Pitfall 5: /metrics Endpoint Counts Itself
**What goes wrong:** Every Prometheus scrape of /metrics increments `pepers_request_count` for the /metrics endpoint, creating self-referential noise.
**Why it happens:** The metrics middleware wraps ALL requests including /metrics.
**How to avoid:** Skip metrics recording for the `/metrics` and `/health` endpoints in _dispatch(). This matches the existing pattern where `/health` doesn't update `last_request_time`.
**Warning signs:** `pepers_request_count{endpoint="/metrics"}` grows at scrape interval rate, dominating actual traffic metrics.

### Pitfall 6: INF Bucket Missing from Custom Buckets
**What goes wrong:** Histogram without `+Inf` bucket causes incorrect _count values.
**Why it happens:** Custom bucket list omits the mandatory `+Inf` (infinity) upper bound.
**How to avoid:** prometheus-client automatically appends `+Inf` to custom bucket lists. No action needed -- but verify this in tests.
**Warning signs:** None (library handles it), but good to know.

## Code Examples

Verified patterns from official sources:

### Creating Counter with Namespace and Labels
```python
# Source: https://prometheus.github.io/client_python/instrumenting/labels/
# Source: https://github.com/prometheus/client_python/blob/master/prometheus_client/metrics.py
from prometheus_client import Counter

REQUEST_COUNT = Counter(
    "request_count",           # metric name (without namespace prefix)
    "Total HTTP requests",     # documentation string
    ["service", "endpoint", "method", "status_code"],  # label names
    namespace="pepers",        # prepends "pepers_" to metric name
)

# Resulting metric name: pepers_request_count_total
# (Counter automatically gets _total suffix)

# Usage with labels (keyword style):
REQUEST_COUNT.labels(
    service="discovery", endpoint="/process",
    method="POST", status_code="200"
).inc()
```

### Creating Histogram with Custom Buckets
```python
# Source: https://prometheus.github.io/client_python/instrumenting/histogram/
from prometheus_client import Histogram

PIPELINE_RUN_DURATION = Histogram(
    "pipeline_run_duration_seconds",
    "Total pipeline run duration in seconds",
    namespace="pepers",
    buckets=(10, 30, 60, 120, 300, 600, 900, 1200, 1800, 3600),
)
# +Inf is appended automatically by the library

# Usage:
PIPELINE_RUN_DURATION.observe(elapsed_seconds)
```

### Creating Gauge
```python
# Source: https://prometheus.github.io/client_python/instrumenting/gauge/
from prometheus_client import Gauge

PIPELINE_RUNS_ACTIVE = Gauge(
    "pipeline_runs_active",
    "Currently active pipeline runs",
    namespace="pepers",
)

# Usage:
PIPELINE_RUNS_ACTIVE.inc()    # +1 when pipeline starts
PIPELINE_RUNS_ACTIVE.dec()    # -1 when pipeline ends (in finally block!)
```

### Generating Metrics Output
```python
# Source: https://github.com/prometheus/client_python/blob/master/prometheus_client/exposition.py
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

output: bytes = generate_latest()  # Returns UTF-8 bytes
content_type: str = CONTENT_TYPE_LATEST
# = "text/plain; version=1.0.0; charset=utf-8"
```

### Histogram Default Buckets (for reference)
```python
# Source: https://github.com/prometheus/client_python/blob/master/prometheus_client/metrics.py
DEFAULT_BUCKETS = (.005, .01, .025, .05, .075, .1, .25, .5, .75, 1.0, 2.5, 5.0, 7.5, 10.0, INF)
```

### Pre-initializing Label Combinations
```python
# Source: https://prometheus.github.io/client_python/instrumenting/labels/
# Pre-initialize to avoid "no data" for services that haven't received traffic
for svc in ("discovery", "analyzer", "extractor", "validator", "codegen", "orchestrator"):
    REQUEST_COUNT.labels(service=svc, endpoint="/health", method="GET", status_code="200")
```

## Implementation Details

### Services and Their Endpoints (for label pre-initialization)

| Service | Port | Endpoints |
|---------|------|-----------|
| discovery | 8770 | POST /process, GET /health, GET /status, GET /metrics |
| analyzer | 8771 | POST /process, GET /health, GET /status, GET /metrics |
| extractor | 8772 | POST /process, GET /health, GET /status, GET /metrics |
| validator | 8773 | POST /process, GET /health, GET /status, GET /metrics |
| codegen | 8774 | POST /process, GET /health, GET /status, GET /metrics |
| orchestrator | 8775 | POST /run, GET /status, GET /status/services, GET /papers, GET /formulas, GET /generated-code, GET /runs, POST /search-github, GET /github-repos, POST /search, GET /health, GET /metrics |
| mcp | 8776 | SSE transport (FastMCP SDK, NOT shared/server.py) |

### MCP Service Note
The MCP service (port 8776) uses FastMCP SDK with SSE transport, **not** the shared/server.py BaseHandler. It cannot participate in the shared metrics middleware. **Recommendation:** Exclude MCP from Phase 44 scope. The orchestrator metrics already capture the work the MCP proxies to.

### Key Instrumentation Points

1. **shared/server.py `_dispatch()`** -- Wrap with timing + counting. This is the single point that handles ALL HTTP requests for 6 services.
2. **shared/server.py `_register_builtins()`** -- Add GET /metrics alongside /health and /status.
3. **services/orchestrator/pipeline.py `PipelineRunner.run()`** -- Instrument total pipeline duration, active runs gauge.
4. **services/orchestrator/pipeline.py stage loop** -- Instrument per-stage duration, stage completion counter.
5. **services/orchestrator/pipeline.py results** -- Extract papers_processed and formulas_validated from stage results to increment counters.

### _dispatch() Instrumentation Design

The current _dispatch() flow:
```
1. Resolve routes (lazy)
2. Find handler
3. If POST: read_json(), call handler(data)
4. If GET: call handler()
5. If result is not None: send_json(result)
6. On exception: send_error_json(str(e), ..., 500)
```

Proposed instrumentation:
```
1. Record start_time = time.monotonic()
2. Set self._response_status = 200 (default)
3. Resolve routes, find handler
4. Skip metrics recording for /metrics and /health paths
5. Execute handler (existing logic)
6. In finally block:
   a. Record duration = time.monotonic() - start_time
   b. Record REQUEST_COUNT.labels(...).inc()
   c. Record REQUEST_DURATION.labels(...).observe(duration)
   d. If status >= 400: ERROR_COUNT.labels(...).inc()
```

Status code tracking: Modify `send_json()` and `send_error_json()` to set `self._response_status` before sending. Read it in the finally block.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| prometheus-client 0.x with CONTENT_TYPE_PLAIN_0_0_4 | prometheus-client 0.24+ with CONTENT_TYPE_LATEST (text/plain; version=1.0.0) | 2024 | Use CONTENT_TYPE_LATEST, not the old 0.0.4 constant |
| Counter without automatic _total suffix | Counter auto-appends _total | prometheus-client 0.14+ | Name your counter "request_count", it becomes "pepers_request_count_total" |
| _created timestamps always exported | Disable via disable_created_metrics() | prometheus-client 0.17+ | Consider disabling for cleaner output (fewer time series) |

**Deprecated/outdated:**
- `CONTENT_TYPE_PLAIN_0_0_4`: Still works but prefer `CONTENT_TYPE_LATEST`
- `start_http_server()` for separate metrics port: Not needed when you already have an HTTP server

## Open Questions

1. **Should we disable _created metrics?**
   - What we know: prometheus-client exports `_created` timestamps for counters/histograms by default. These add extra time series.
   - What's unclear: Whether the extra time series matter for PePeRS' scale (7 services, ~20 metrics total).
   - Recommendation: Leave default (enabled). Overhead is negligible at this scale. If needed later, one-line change: `disable_created_metrics()`.

2. **Metric persistence across restarts?**
   - What we know: Prometheus scrapes metrics at intervals. If a service restarts, counters reset to 0. Prometheus handles this via `rate()` and `increase()` functions that detect counter resets.
   - What's unclear: Nothing -- this is well-understood Prometheus behavior.
   - Recommendation: No action needed. Counters reset on restart is expected and handled by Prometheus.

## Sources

### Primary (HIGH confidence)
- prometheus-client PyPI page (v0.24.1, released 2026-01-14) - version, Python compatibility
- prometheus-client GitHub source (metrics.py) - Constructor signatures, DEFAULT_BUCKETS, thread safety (Lock-based)
- prometheus-client GitHub source (exposition.py) - generate_latest() signature, CONTENT_TYPE_LATEST value
- prometheus-client official docs (instrumenting/) - Counter, Histogram, Gauge, Labels API
- prometheus-client official docs (exporting/http/) - MetricsHandler, start_http_server, HTTPS support

### Secondary (MEDIUM confidence)
- Prometheus naming conventions (prometheus.io/docs/practices/naming/) - namespace parameter behavior verified with GitHub issue #712
- PePeRS codebase direct inspection - shared/server.py, all 6 service main.py files, pipeline.py, config.py

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - prometheus-client is the single library, version verified on PyPI, API verified from source code
- Architecture: HIGH - shared/server.py is a known single integration point, codebase fully inspected
- Pitfalls: HIGH - based on direct code analysis of _dispatch() flow and known prometheus-client behaviors from official docs

**Research date:** 2026-02-21
**Valid until:** 2026-03-21 (prometheus-client is stable, PePeRS architecture is stable)
