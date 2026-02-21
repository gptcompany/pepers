# Architecture Research: Production Hardening

## Current Architecture

```
shared/server.py → BaseService → HTTPServer (single-threaded)
                 → BaseHandler → @route dispatch
                 → JsonFormatter → JSON logs to stdout

docker-compose.yml → 7 services (discovery, analyzer, extractor, validator, codegen, orchestrator, mcp)
                   → network_mode: host (all on localhost)
                   → restart: unless-stopped
                   → health checks every 30s

monitoring-stack/ → VictoriaMetrics (:8428, Prometheus-compatible)
                 → Grafana (:3000) with provisioned dashboards
                 → Loki (:3100) + Promtail
                 → process-exporter (:9256) → Prometheus scrape
```

## Integration Points

### 1. Prometheus Metrics Exposition

**Where:** `shared/server.py` — add `/metrics` endpoint to BaseHandler.
**How:** `prometheus_client` library. Each service auto-exposes:
- `pepers_requests_total{service, method, endpoint, status}` — Counter
- `pepers_request_duration_seconds{service, endpoint}` — Histogram
- `pepers_errors_total{service, error_type}` — Counter

Service-specific metrics registered in each service's handler (e.g., orchestrator adds `pepers_papers_processed_total`).

**Prometheus config:** Add scrape job for each PePeRS service port (8770-8776) in `prometheus/prometheus.yml`:
```yaml
- job_name: 'pepers'
  static_configs:
    - targets: ['localhost:8770', 'localhost:8771', ..., 'localhost:8776']
```

### 2. process-exporter Config

**Where:** `/media/sam/1TB/monitoring-stack/process-exporter/config.yml`
**Current:** Python matched as `python-{script}` → all PePeRS services show as `python-main.py`.
**Fix:** Add PePeRS-specific rule BEFORE the generic python rule:
```yaml
- name: "pepers-{{.Matches.svc}}"
  cmdline:
  - python
  - services\.(?P<svc>discovery|analyzer|extractor|validator|codegen|orchestrator|mcp)
```

### 3. ThreadingHTTPServer

**Where:** `shared/server.py:318` — change `HTTPServer` → `ThreadingHTTPServer`.
**Import:** Add `ThreadingHTTPServer` to import from `http.server`.
**Thread safety concerns:**
- `BaseHandler` class-level attrs (`last_request_time`, `_routes`) — `_routes` is built once then read-only. `last_request_time` is write-once per request, race is benign.
- SQLite: `shared/db.py` `get_connection()` creates new connection each call — thread-safe as-is IF each handler call gets its own connection and doesn't share.
- `prometheus_client` counters/histograms are thread-safe by design.

### 4. Request Body Size Limit

**Where:** `shared/server.py` `read_json()` method (line ~189).
**How:** Add `MAX_BODY_SIZE` constant. Check `Content-Length` header before `rfile.read()`:
```python
MAX_BODY_SIZE = 10 * 1024 * 1024  # 10 MB
if content_length > MAX_BODY_SIZE:
    self.send_error_json("Request body too large", "BODY_TOO_LARGE", 413)
    return None
```

### 5. Stuck-State Cleanup

**Where:** `services/orchestrator/pipeline.py` or `services/orchestrator/main.py` at startup.
**How:** On orchestrator startup, query `pipeline_runs` for status='running'. Mark them as 'failed' with reason='server_restart'. This prevents phantom "in-progress" runs.

### 6. Grafana Dashboard

**Where:** `/media/sam/1TB/monitoring-stack/grafana/provisioning/dashboards/pepers.json`
**Provisioning:** Already configured via `dashboards.yml`. Just add JSON file.
**Panels:**
1. Service Health (stat panel — up/down per service)
2. Papers Processed (time series — daily count)
3. Pipeline Stage Duration (bar gauge — avg per stage)
4. Error Rate (time series — errors/hour per service)
5. Formula Validation Results (pie — valid/invalid/unparseable)
6. Active Pipeline Runs (stat)

### 7. Docker Production Hardening

**Where:** `docker-compose.yml`
**Changes:**
- Add `logging` section with `json-file`, `max-size: 10m`, `max-file: 3`
- Add `deploy.resources.limits` (memory: 512m per service, 1g for orchestrator)
- Add `stop_grace_period: 30s`

### 8. Auto-Start at Boot

**Where:** Systemd unit file.
**How:** `pepers.service` that runs `docker compose -f /media/sam/1TB/pepers/docker-compose.yml up -d`.
**Note:** `deploy/` already has systemd units for non-Docker mode. For Docker, need one systemd unit for Docker Compose.

## Suggested Build Order

1. **ThreadingHTTPServer + body size limit** (shared/server.py — affects all services, no external deps)
2. **Stuck-state cleanup** (orchestrator startup — self-contained)
3. **prometheus-client + /metrics** (shared/server.py + each service — new dependency)
4. **Docker hardening** (docker-compose.yml — log rotation, limits, auto-start)
5. **Monitoring integration** (process-exporter, Prometheus scrape, alerts, dashboard — external configs)
6. **Testing** (E2E tests for all changes)

This order ensures each step builds on the previous without blockers.
