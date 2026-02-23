#!/usr/bin/env bash
# Deploy PePeRS monitoring configs to the monitoring stack.
# Run with sudo: sudo ./monitoring/deploy.sh
set -euo pipefail

MONITORING_STACK="/media/sam/1TB/monitoring-stack"
PROM_DEST="/etc/prometheus"
GRAFANA_PROV="/etc/grafana/provisioning"

echo "=== PePeRS Monitoring Deploy ==="

# 1. Copy prometheus.yml
echo "[1/5] Deploying prometheus.yml..."
cp "$MONITORING_STACK/prometheus/prometheus.yml" "$PROM_DEST/prometheus.yml"
echo "  -> $PROM_DEST/prometheus.yml"

# 2. Copy alert rules
echo "[2/5] Deploying alert.rules.yml..."
cp "$MONITORING_STACK/prometheus/alert.rules.yml" "$PROM_DEST/alert.rules.yml"
echo "  -> $PROM_DEST/alert.rules.yml"

# 3. Grafana dashboard provisioning (points to monitoring-stack dashboards dir)
echo "[3/5] Deploying Grafana dashboard provisioning..."
cat > "$GRAFANA_PROV/dashboards/pepers.yaml" <<'EOF'
apiVersion: 1

providers:
  - name: 'PePeRS Pipeline'
    orgId: 1
    folder: 'PePeRS'
    folderUid: 'pepers'
    type: file
    disableDeletion: false
    updateIntervalSeconds: 30
    options:
      path: /media/sam/1TB/monitoring-stack/grafana/dashboards
EOF
echo "  -> $GRAFANA_PROV/dashboards/pepers.yaml"

# 4. Restart services
echo "[4/5] Restarting services..."
systemctl restart process-exporter
echo "  -> process-exporter restarted"
systemctl restart victoria-metrics
echo "  -> victoria-metrics restarted"
systemctl restart grafana-server
echo "  -> grafana-server restarted"

# 5. Verify
echo "[5/5] Verifying..."
sleep 3
systemctl is-active --quiet grafana-server && echo "  -> Grafana: OK" || echo "  !! Grafana: FAILED"
systemctl is-active --quiet victoria-metrics && echo "  -> VictoriaMetrics: OK" || echo "  !! VictoriaMetrics: FAILED"

echo ""
echo "=== Deploy Complete ==="
echo "Dashboard: http://localhost:3000/d/pepers-pipeline"
echo "Targets:   curl -s localhost:8428/api/v1/targets | python3 -m json.tool | grep pepers"
