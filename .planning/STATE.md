# State: PePeRS

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-21)

**Core value:** Reliable, N8N-free academic paper processing pipeline
**Current focus:** v13.0 Production Hardening — COMPLETE

## Current Position

Phase: 46 of 46 (Monitoring Integration)
Plan: 2 of 2 in current phase
Status: Milestone complete
Last activity: 2026-02-23 — Phase 46 plans 1-2 completed

Progress: [██████████] 100% (6/6 plans)

## Performance Metrics

**Velocity:**
- Total plans completed: 6 (v13.0)
- Average duration: ~11min
- Total execution time: ~11min (measured)

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 43 | 2/2 | — | — |
| 44 | 1/1 | 11min | 11min |
| 45 | 1/1 | — | — |
| 46 | 2/2 | — | — |

**Recent Trend:**
- Last 5 plans: 44-01, 45-01, 46-01, 46-02
- Trend: stable

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [v13.0]: ThreadingHTTPServer over async (stdlib, zero deps, matches existing pattern)
- [v13.0]: prometheus-client is only new dependency (~60KB)
- [v13.0]: shared/server.py is single change point for threading + body limits + metrics
- [v13.0]: MCP server (FastMCP SDK) NOT affected by shared/server.py changes
- [Phase 43]: Body size limit checks Content-Length BEFORE reading rfile (prevents DoS)
- [Phase 43]: All 'running' pipeline runs cleaned unconditionally at startup (single-instance, all are orphaned)
- [Phase 43]: daemon_threads=True on ThreadingHTTPServer for clean shutdown
- [Phase 44]: Counter names omit _total suffix (prometheus-client appends automatically)
- [Phase 44]: /metrics and /health excluded from request counting to prevent self-counting noise
- [Phase 45]: YAML extension fields for DRY Docker config (x-logging, x-deploy-*)
- [Phase 45]: No systemd unit needed — Docker daemon already systemd-enabled
- [Phase 45]: init: true on all containers for proper signal forwarding
- [Phase 46]: honor_labels: true in Prometheus scrape config to preserve PePeRS service labels
- [Phase 46]: Grafana provisioned alerting instead of Prometheus rules (VictoriaMetrics has no vmalert)
- [Phase 46]: Dashboard provisioned from monitoring-stack/grafana/dashboards/ via pepers.yaml

### Pending Todos

None.

### Blockers/Concerns

- SQLite thread safety: VERIFIED — get_connection() creates new connection per call in all services
- Prometheus label cardinality: NEVER use paper_id/formula_id as labels
- Docker log rotation requires --force-recreate on existing containers
- VictoriaMetrics does not evaluate alert rules (no vmalert) — using Grafana provisioned alerting

## Session Continuity

Last session: 2026-02-23
Stopped at: Milestone v13.0 complete (all 6 plans across 4 phases)
Resume file: None
