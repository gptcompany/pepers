# Phase 46, Plan 01 Summary: process-exporter + Prometheus scrape + alert rules

## Outcome: Complete

## What was done

### 1. process-exporter config
- **File:** `/media/sam/1TB/monitoring-stack/process-exporter/config.yml`
- Added PePeRS regex entry **before** generic Python catchall
- Pattern: `python\s+-m\s+services\.(?P<svc>discovery|analyzer|extractor|validator|codegen|orchestrator)\.main`
- Each container appears as `pepers-{svc}` (e.g. `pepers-discovery`)

### 2. Prometheus scrape config
- **File:** `/media/sam/1TB/monitoring-stack/prometheus/prometheus.yml`
- Added `pepers` scrape job with 6 targets (ports 8770-8775)
- `honor_labels: true` to preserve PePeRS' own `service` label
- Labels: `machine: workstation`, `env: local`

### 3. Alert rules (Prometheus-format + Grafana provisioned)
- **Prometheus-format** (in `alert.rules.yml`): `PepersServiceDown` (3m) and `PepersNoPapersProcessed` (24h window, 5m for)
  - Note: VictoriaMetrics single-node does NOT evaluate alert rules (no vmalert); these are for future use if vmalert is added
- **Grafana provisioned alerting** (deployed to `/etc/grafana/provisioning/alerting/pepers-alert-rules.yaml`):
  - `pepers-service-down`: threshold on `up{job="pepers"} < 1`, severity=critical, for 3m
  - `pepers-no-papers`: threshold on `increase(pepers_papers_processed_total[24h]) < 1`, severity=warning, for 5m
  - Both rules active in Grafana (verified via API: 70 total rules loaded)

### 4. Deploy script
- **File:** `/media/sam/1TB/pepers/monitoring/deploy.sh`
- Copies prometheus.yml and alert.rules.yml to /etc/prometheus/
- Restarts process-exporter and victoria-metrics

## Verification

- VictoriaMetrics targets: 6 PePeRS targets visible at `http://localhost:8428/api/v1/targets`
- Started discovery container → target switched to `up` within 30s scrape cycle
- Grafana alert rules: both PePeRS rules loaded (confirmed via `/api/v1/provisioning/alert-rules`)
- All 828 project tests pass with no regressions

## Key decisions

- VictoriaMetrics doesn't evaluate Prometheus alerting rules (no vmalert component) → used Grafana provisioned alerting instead
- Alert rules also kept in Prometheus format in alert.rules.yml for future vmalert adoption
- Fixed pre-existing broken Grafana symlink (`hyperliquid-alert-rules.yaml` → non-existent nautilus_dev path) that was crashing Grafana
