# Stack Research: Production Hardening

## Current Stack (DO NOT re-research)

- Python stdlib `http.server.HTTPServer` (single-threaded) in `shared/server.py`
- Docker Compose with `network_mode: host`, `restart: unless-stopped`
- Monitoring stack: VictoriaMetrics (Prometheus-compatible on :8428), Grafana (:3000), Loki (:3100), process-exporter (:9256)
- JSON structured logging via `JsonFormatter` in `shared/server.py`

## Stack Additions Needed

### 1. ThreadingHTTPServer (stdlib — zero new deps)

**What:** Replace `HTTPServer` with `ThreadingHTTPServer` from `http.server` (same module).
**Why:** `HTTPServer` processes one request at a time. Multiple MCP clients block each other.
**Integration:** One-line change in `shared/server.py:318` — `HTTPServer(...)` → `ThreadingHTTPServer(...)`.
**Thread safety:** SQLite connections are NOT thread-safe. Each thread must create its own connection. Current `shared/db.py` uses `get_connection()` which creates new connections — verify it's called per-request, not cached globally.

### 2. Prometheus Client (prometheus-client pypi — NEW dep)

**What:** `prometheus_client` Python library for `/metrics` endpoint exposition.
**Why:** Native Prometheus metrics format. Process-exporter gives process-level metrics; this gives application-level metrics (papers processed, formula counts, errors, latency histograms).
**Version:** prometheus-client 0.21.x (latest stable, Python 3.8+).
**Integration:** Add `/metrics` endpoint to `shared/server.py`. Expose counters/histograms that each service increments.
**Alternative considered:** Custom `/metrics` text endpoint without library → too error-prone for histogram buckets and exposition format. Library is 60KB, well-maintained.

### 3. process-exporter config (existing — config change only)

**What:** Add PePeRS service matching rules to `/media/sam/1TB/monitoring-stack/process-exporter/config.yml`.
**Current state:** Python processes matched as `python-{script}`. Docker containers matched as generic `docker-container`. Neither identifies PePeRS services individually.
**For Docker:** With `network_mode: host`, PePeRS processes appear as host processes (not containerized from process-exporter's view). The existing `python-{script}` rule will match them as `python-main.py` — but ALL services have `main.py`. Need cmdline matching by module: `-m services.discovery`, `-m services.analyzer`, etc.

### 4. Grafana Dashboard (JSON model — no new deps)

**What:** Provisioned dashboard JSON at `/media/sam/1TB/monitoring-stack/grafana/provisioning/dashboards/pepers.json`.
**Current provisioning:** `dashboards.yml` config loads JSON files from a directory. Add `pepers.json` alongside existing `cron-jobs.json`, `operations-center.json`, etc.
**Datasource:** VictoriaMetrics via "Prometheus" datasource (already configured, url: `http://localhost:8428`).

### 5. Prometheus Alert Rules (YAML — no new deps)

**What:** Alert rules YAML file referenced from VictoriaMetrics/Prometheus config.
**Integration:** Add rules file and reference in prometheus/vmagent config.

### 6. Docker log driver (config change only)

**What:** Add `logging` section to docker-compose.yml for log rotation.
**Current state:** No log driver specified → defaults to `json-file` with no rotation → logs grow unbounded.
**Fix:** `json-file` with `max-size: 10m`, `max-file: 3`.

## What NOT to Add

- **aiohttp/FastAPI/uvicorn** — YAGNI. ThreadingHTTPServer is sufficient for ~10 papers/day + a few MCP clients.
- **Redis/message queue** — Still not needed. HTTP sync pipeline is fine.
- **Custom metrics exporter binary** — prometheus-client library is simpler and more maintainable.
- **Separate metrics service** — Each service exposes its own `/metrics`. No aggregation layer needed.
