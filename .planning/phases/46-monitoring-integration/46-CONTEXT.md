# Context: Phase 46 — Monitoring Integration

## Phase Goal

PePeRS pipeline health is visible in Grafana with automatic alerts on failures.

## Requirements

- **MON-03**: process-exporter shows each PePeRS service as a distinct named group (not generic "python")
- **MON-04**: Prometheus targets page shows all PePeRS services as UP
- **MON-05**: Grafana dashboard displays 6 panels: service health, throughput (papers/day), latency per stage, error rates, formula validation results, active pipeline runs
- **MON-06**: Prometheus alert fires within 3 minutes when a PePeRS service is stopped, and another fires if no papers are processed for 24 hours

## Monitoring Stack Architecture

All monitoring runs on Workstation (192.168.1.111):

- **VictoriaMetrics** (:8428) — TSDB + Prometheus-compatible scraper, reads `/etc/prometheus/prometheus.yml`
- **process-exporter** (:9256) — native systemd, config at `/media/sam/1TB/monitoring-stack/process-exporter/config.yml`
- **Alertmanager** (:9093) — native systemd, config at `/etc/alertmanager/alertmanager.yml`
- **Grafana** (:3000) — native systemd, provisioned dashboards from `/media/sam/1TB/monitoring-stack/grafana/dashboards/`
- **Alert rules** — `/etc/prometheus/alert.rules.yml` (read by VictoriaMetrics)

**Key**: VictoriaMetrics replaces Prometheus. Uses same config format. Scrape config and alert rules are Prometheus-format YAML.

**Source of truth**: `/media/sam/1TB/monitoring-stack/` repo. Files get copied to `/etc/prometheus/` for deployment.

## PePeRS Metrics (from Phase 44)

All services expose GET /metrics in Prometheus text format on their ports:

| Service | Port | Metrics Prefix |
|---------|------|---------------|
| discovery | 8770 | pepers_ |
| analyzer | 8771 | pepers_ |
| extractor | 8772 | pepers_ |
| validator | 8773 | pepers_ |
| codegen | 8774 | pepers_ |
| orchestrator | 8775 | pepers_ |

**Shared metrics** (all services):
- `pepers_request_count_total{service, method, path, status}`
- `pepers_request_duration_seconds{service, method, path}` (histogram)
- `pepers_error_count_total{service, error_type}`

**Orchestrator-specific**:
- `pepers_pipeline_run_duration_seconds` (histogram)
- `pepers_pipeline_stage_duration_seconds{stage}` (histogram)
- `pepers_pipeline_stage_completed_total{stage, outcome}` (counter: success/failure/skip)
- `pepers_pipeline_runs_active` (gauge)
- `pepers_papers_processed_total` (counter)
- `pepers_formulas_validated_total` (counter)

## What Needs to Change

### Plan 46-01: process-exporter + Prometheus scrape + alert rules

**1. process-exporter config** (`/media/sam/1TB/monitoring-stack/process-exporter/config.yml`)

Add PePeRS service entries. PePeRS runs in Docker containers as `python -m services.{name}.main`. Inside Docker, process-exporter sees these via PID namespace (host mode). The cmdline pattern:
```
python -m services.discovery.main
python -m services.analyzer.main
...
```

Need named groups like `pepers-discovery`, `pepers-analyzer`, etc.

The existing Python catchall (`python-{{.Matches.script}}`) would match PePeRS processes but name them generically. Need a HIGHER PRIORITY entry before the Python catchall.

**2. Prometheus scrape config** (`/media/sam/1TB/monitoring-stack/prometheus/prometheus.yml` → copied to `/etc/prometheus/prometheus.yml`)

Add one scrape job with all PePeRS targets. Use `honor_labels: true` to preserve PePeRS' own `service` label (discovery, analyzer, etc.) instead of overwriting it:
```yaml
- job_name: 'pepers'
  honor_labels: true
  static_configs:
    - targets: ['localhost:8770', 'localhost:8771', 'localhost:8772', 'localhost:8773', 'localhost:8774', 'localhost:8775']
      labels:
        machine: 'workstation'
        env: 'local'
```

Each PePeRS /metrics already emits `service="discovery"`, `service="analyzer"`, etc. With `honor_labels: true`, the per-service identity is preserved. The scrape job adds `instance` (host:port), `job`, `machine`, and `env`.

**3. Alert rules** (`/etc/prometheus/alert.rules.yml`)

Add `pepers_alerts` group:
- `PepersServiceDown`: `up{job="pepers"} == 0` for 3m (severity: critical)
- `PepersNoPapersProcessed`: `increase(pepers_papers_processed_total[24h]) == 0` for 1h (severity: warning) — short `for` since `increase[24h]` already covers the window

**4. Deploy script** (`monitoring/deploy.sh` in PePeRS repo)

Copies configs to monitoring stack and reloads services:
- Appends PePeRS entries to process-exporter config
- Adds scrape job to prometheus.yml
- Adds alert rules to alert.rules.yml
- Copies dashboard to Grafana dashboards dir
- Reloads VictoriaMetrics + process-exporter

### Plan 46-02: Grafana dashboard

**Dashboard JSON** at `/media/sam/1TB/monitoring-stack/grafana/dashboards/pepers-pipeline.json`

6 panels:
1. **Service Health** — `up{job="pepers"}` stat panel (UP/DOWN per service)
2. **Throughput** — `increase(pepers_papers_processed_total[24h])` stat panel
3. **Latency per Stage** — `rate(pepers_pipeline_stage_duration_seconds_sum[5m]) / rate(pepers_pipeline_stage_duration_seconds_count[5m])` heatmap/bar
4. **Error Rates** — `rate(pepers_error_count_total[5m])` time series
5. **Formula Validation** — `increase(pepers_formulas_validated_total[24h])` stat + `pepers_pipeline_stage_completed_total{stage="validator"}` by outcome
6. **Active Pipeline Runs** — `pepers_pipeline_runs_active` gauge

**Datasource**: "Prometheus" (VictoriaMetrics at :8428)

## Deployment Steps

After creating config, need to:
1. Reload VictoriaMetrics: `kill -HUP $(pgrep victoria-metrics)` or restart service
2. Restart process-exporter: `sudo systemctl restart process-exporter`
3. Grafana auto-reloads dashboards every 30s (provisioning config)

## Risks

1. **process-exporter PID namespace**: process-exporter runs natively on host (systemd), reads /proc directly. Docker container processes ARE visible in host /proc (high PIDs, separate namespace but still visible from host). VERIFIED: no `pid: host` needed on containers, only the exporter needs /proc access (which it has natively). (LOW)
2. **VictoriaMetrics alert rules**: VM supports Prometheus alert rules format but some functions may differ (LOW)
3. **Label collision**: PePeRS `/metrics` includes `service` label; Prometheus scrape may also add labels — verify no collision (LOW)

## Success Criteria (from ROADMAP.md)

1. process-exporter shows each PePeRS service as a distinct named group (not generic "python") in Prometheus
2. Prometheus targets page shows all PePeRS services as UP
3. Grafana dashboard displays 6 panels: service health, throughput, latency per stage, error rates, formula validation, active pipeline runs
4. Prometheus alert fires within 3 minutes when a PePeRS service is stopped, and another fires if no papers are processed for 24 hours
