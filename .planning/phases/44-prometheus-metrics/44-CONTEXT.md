# Phase 44: Prometheus Metrics - Context

**Gathered:** 2026-02-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Every PePeRS service exposes machine-readable performance metrics that Prometheus can scrape. GET /metrics on each service (ports 8770-8776) returns Prometheus text format. This phase instruments the existing services — Prometheus scraping config and Grafana dashboards belong in Phase 46.

</domain>

<decisions>
## Implementation Decisions

### Label Granularity
- Labels per metrica HTTP: `service`, `endpoint`, `method`, `status_code`
- `service` = nome logico (discovery, analyzer, extractor, validator, codegen, orchestrator) — non porta
- `endpoint` = path HTTP completo (es. `/discover`, `/analyze`, `/metrics`)
- Namespace prefix: `pepers_` su tutte le metriche (es. `pepers_request_count`, `pepers_request_duration_seconds`)

### Pipeline Stage Breakdown
- Orchestrator espone metriche per-stage oltre ai totali pipeline
- `pepers_stage_duration_seconds{stage="discovery"}` histogram per ogni stage
- `pepers_stage_completed_total{stage="validator", result="success|failure|skipped"}` counter con label result
- `pepers_pipeline_runs_active` gauge per pipeline run attivi in tempo reale
- Stages: discovery, analyzer, extractor, validator, codegen

### Histogram Buckets
- Request HTTP (singoli servizi): default prometheus-client (0.005 - 10s)
- Pipeline run duration: custom buckets (10, 30, 60, 120, 300, 600, 1800, 3600s) per coprire durate da 1 min a 1 ora
- Stage duration: custom buckets da definire in base ai tempi tipici per stage

### Claude's Discretion
- Error classification approach (per-type labels vs contatore unico vs status-code-only)
- LLM fallback tracking (valutare se rientra in scope o se rimandare a MONX-01)
- CAS error counter separato vs catturato in stage result
- Counter dedicato per 413 rejected vs catturato in request_count con status_code=413
- Formulas-per-paper histogram vs solo totale
- Scelta dei bucket per stage_duration_seconds

</decisions>

<specifics>
## Specific Ideas

- Metriche devono essere compatibili con i 6 pannelli Grafana previsti in Phase 46: service health, throughput (papers/day), latency per stage, error rates, formula validation results, active pipeline runs
- Il middleware metriche va in shared/server.py (single change point, come da decisione Phase 43)
- prometheus-client e' l'unica dipendenza nuova (~60KB, gia' prevista)

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 44-prometheus-metrics*
*Context gathered: 2026-02-21*
