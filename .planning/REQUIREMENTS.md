# Requirements: PePeRS

**Defined:** 2026-02-21
**Core Value:** Reliable, N8N-free academic paper processing pipeline

## v13.0 Requirements

Requirements for production hardening. Each maps to roadmap phases.

### Concurrency

- [ ] **CONC-01**: All 6 microservices handle concurrent requests via ThreadingHTTPServer
- [ ] **CONC-02**: Request body size is limited to 10MB with 413 error on exceeding
- [ ] **CONC-03**: SQLite connections are verified thread-safe (per-request, no caching)

### Monitoring

- [ ] **MON-01**: Each service exposes /metrics endpoint with Prometheus format (request count, duration histogram, error count)
- [ ] **MON-02**: Orchestrator exposes pipeline-specific metrics (papers processed, formulas validated, run duration)
- [ ] **MON-03**: process-exporter identifies PePeRS services individually (not generic python-main.py)
- [ ] **MON-04**: Prometheus scrapes all PePeRS /metrics endpoints (8770-8776)
- [ ] **MON-05**: Grafana dashboard shows pipeline health (6 panels: service health, throughput, latency, errors, formula results, active runs)
- [ ] **MON-06**: Prometheus alerts fire on service down (>2 min), pipeline stalled (>24h no papers), high error rate (>50%)

### Deployment

- [ ] **DEP-01**: Docker logs rotate automatically (json-file, 10MB max, 3 files)
- [ ] **DEP-02**: Docker containers have memory limits (512MB per service, 1GB orchestrator)
- [ ] **DEP-03**: PePeRS Docker Compose auto-starts at boot via systemd unit
- [ ] **DEP-04**: Services shut down gracefully with 30s stop_grace_period

### Resilience

- [ ] **RES-01**: Orchestrator startup cleans stuck pipeline_runs (running >5min → failed with reason)

## Future Requirements

### Performance

- **PERF-01**: Connection pooling for SQLite (if thread contention becomes measurable)
- **PERF-02**: Async HTTP server (if ThreadingHTTPServer proves insufficient)

### Monitoring Extensions

- **MONX-01**: LLM provider usage tracking (which fallback provider used, latency)
- **MONX-02**: CAS engine health monitoring per engine
- **MONX-03**: Disk usage alerts for PDF storage and SQLite DB

## Out of Scope

| Feature | Reason |
|---------|--------|
| Auto-scaling | ~10 papers/day, single machine. YAGNI. |
| Distributed tracing (Jaeger/Tempo) | Batch pipeline, not request-driven. YAGNI. |
| Custom alertmanager integrations | Discord webhook already works via apprise. |
| Web UI for monitoring | Grafana handles visualization. |
| Rate limiting per client | Internal services + MCP only, no public API. |
| aiohttp/FastAPI migration | ThreadingHTTPServer sufficient for current load. |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| CONC-01 | — | Pending |
| CONC-02 | — | Pending |
| CONC-03 | — | Pending |
| MON-01 | — | Pending |
| MON-02 | — | Pending |
| MON-03 | — | Pending |
| MON-04 | — | Pending |
| MON-05 | — | Pending |
| MON-06 | — | Pending |
| DEP-01 | — | Pending |
| DEP-02 | — | Pending |
| DEP-03 | — | Pending |
| DEP-04 | — | Pending |
| RES-01 | — | Pending |

**Coverage:**
- v13.0 requirements: 14 total
- Mapped to phases: 0
- Unmapped: 14 ⚠️

---
*Requirements defined: 2026-02-21*
*Last updated: 2026-02-21 after initial definition*
