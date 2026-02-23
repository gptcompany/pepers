#!/usr/bin/env bash
# Deploy PePeRS monitoring configs to the monitoring stack.
# Run with sudo: sudo ./monitoring/deploy.sh
set -euo pipefail

MONITORING_STACK="/media/sam/1TB/monitoring-stack"
PROM_DEST="/etc/prometheus"

echo "=== PePeRS Monitoring Deploy ==="

# 1. Copy prometheus.yml
echo "[1/3] Deploying prometheus.yml..."
cp "$MONITORING_STACK/prometheus/prometheus.yml" "$PROM_DEST/prometheus.yml"
echo "  -> $PROM_DEST/prometheus.yml"

# 2. Copy alert rules
echo "[2/3] Deploying alert.rules.yml..."
cp "$MONITORING_STACK/prometheus/alert.rules.yml" "$PROM_DEST/alert.rules.yml"
echo "  -> $PROM_DEST/alert.rules.yml"

# 3. Restart services
echo "[3/3] Restarting services..."
systemctl restart process-exporter
echo "  -> process-exporter restarted"
systemctl restart victoria-metrics
echo "  -> victoria-metrics restarted"

echo ""
echo "=== Deploy Complete ==="
echo "Grafana dashboard auto-reloads from: $MONITORING_STACK/grafana/dashboards/"
echo "Verify targets: curl -s localhost:8428/api/v1/targets | python3 -m json.tool | grep pepers"
