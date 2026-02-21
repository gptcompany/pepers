# Features Research: Production Hardening

## Feature Categories

### Monitoring — Table Stakes

| Feature | Complexity | Notes |
|---------|-----------|-------|
| Service up/down detection | Low | Process-exporter + alert rule |
| Pipeline throughput (papers/day) | Low | Counter metric in orchestrator |
| Error rate per stage | Medium | Counter per service, label by error type |
| Response time per stage | Medium | Histogram metric per endpoint |
| Grafana dashboard | Medium | JSON provisioned, 4-6 panels |
| Prometheus alert: service down | Low | PromQL on process-exporter or /health probe |
| Prometheus alert: pipeline stalled | Low | Alert if no papers processed in 24h |

### Monitoring — Differentiators

| Feature | Complexity | Notes |
|---------|-----------|-------|
| Formula success rate (valid/invalid/unparseable) | Low | Counter from validator |
| CAS engine health | Low | Check CAS :8769 /health from validator |
| LLM fallback tracking | Medium | Counter per LLM provider used |
| Pipeline run duration histogram | Medium | Timer in orchestrator |
| Disk usage for PDFs/DB | Low | Node exporter already provides this |

### Deployment — Table Stakes

| Feature | Complexity | Notes |
|---------|-----------|-------|
| Log rotation (Docker json-file) | Low | Add logging config to docker-compose.yml |
| Auto-start at boot | Low | systemd unit for `docker compose up` |
| Restart policies | Already done | `restart: unless-stopped` already in docker-compose.yml |
| Health check tuning | Low | Already have health checks, may need timing adjustments |

### Deployment — Differentiators

| Feature | Complexity | Notes |
|---------|-----------|-------|
| Resource limits (memory/CPU) | Low | `deploy.resources.limits` in docker-compose.yml |
| Graceful shutdown ordering | Low | Docker Compose `stop_grace_period` |

### Concurrency — Table Stakes

| Feature | Complexity | Notes |
|---------|-----------|-------|
| ThreadingHTTPServer for all services | Low | One-line change in shared/server.py |
| Thread-safe DB access | Medium | Verify per-request connections, no shared state |
| Request body size limit | Low | Check Content-Length before reading in read_json() |

### Resilience — Table Stakes

| Feature | Complexity | Notes |
|---------|-----------|-------|
| Stuck-state cleanup on startup | Medium | Orchestrator checks for "running" runs at boot → mark failed |
| Pipeline run timeout | Low | Max duration per run, orchestrator kills if exceeded |

### Anti-Features (Do NOT build)

| Feature | Why Not |
|---------|---------|
| Auto-scaling | ~10 papers/day, single machine |
| Distributed tracing (Jaeger/Tempo) | YAGNI for batch pipeline |
| Custom alertmanager integrations | Discord webhook already works |
| Web UI for monitoring | Grafana handles this |
| Rate limiting per client | Only internal services + MCP, no public API |
