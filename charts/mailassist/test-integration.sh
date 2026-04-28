#!/usr/bin/env bash
# =============================================================================
# Helm Chart Integration Test — Local Kubernetes (Docker Desktop)
# =============================================================================
# Installs the chart into a temporary namespace, validates all resources come up
# healthy, and cleans up afterwards.
#
# Usage:
#   ./charts/mailassist/test-integration.sh [values-file]
#
# If no values file is given, uses charts/mailassist/ci/default-values.yaml.
# =============================================================================
set -euo pipefail

CHART_DIR="$(cd "$(dirname "$0")" && pwd)"
RELEASE="mailassist-test"
NAMESPACE="mailassist-test"
VALUES="${1:-${CHART_DIR}/ci/default-values.yaml}"
TIMEOUT="120s"
PASSED=0
FAILED=0

# -- Colors ----------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
fail() { echo -e "${RED}[✗]${NC} $*"; }

pass() { ((PASSED++)); log "$1"; }
err()  { ((FAILED++)); fail "$1"; }

# -- Cleanup ----------------------------------------------------------------
cleanup() {
    echo ""
    warn "Cleaning up..."
    helm uninstall "$RELEASE" -n "$NAMESPACE" --wait 2>/dev/null || true
    kubectl delete namespace "$NAMESPACE" --wait=false 2>/dev/null || true
    log "Cleanup done."
}
trap cleanup EXIT

# -- Preflight checks -------------------------------------------------------
echo "============================================="
echo " MailAssist Helm Integration Test"
echo "============================================="
echo ""

for cmd in helm kubectl; do
    if ! command -v "$cmd" &>/dev/null; then
        fail "$cmd is not installed"
        exit 1
    fi
done

if ! kubectl cluster-info &>/dev/null; then
    fail "No Kubernetes cluster reachable. Is Docker Desktop K8s enabled?"
    exit 1
fi
log "Cluster reachable: $(kubectl config current-context)"

if [ ! -f "$VALUES" ]; then
    fail "Values file not found: $VALUES"
    exit 1
fi
log "Using values: $VALUES"
echo ""

# -- Step 1: Lint ------------------------------------------------------------
echo "--- Lint ---"
if helm lint "$CHART_DIR" -f "$VALUES" --strict; then
    pass "helm lint passed"
else
    err "helm lint failed"
fi
echo ""

# -- Step 2: Template render -------------------------------------------------
echo "--- Template render ---"
if helm template "$RELEASE" "$CHART_DIR" -f "$VALUES" --namespace "$NAMESPACE" > /dev/null 2>&1; then
    pass "helm template renders without errors"
else
    err "helm template failed"
fi
echo ""

# -- Step 3: Install ---------------------------------------------------------
echo "--- Install ---"
kubectl create namespace "$NAMESPACE" 2>/dev/null || true

if helm install "$RELEASE" "$CHART_DIR" \
    -f "$VALUES" \
    -n "$NAMESPACE" \
    --wait \
    --timeout "$TIMEOUT"; then
    pass "helm install succeeded"
else
    err "helm install failed"
    echo ""
    warn "Pod status:"
    kubectl get pods -n "$NAMESPACE" -o wide
    echo ""
    warn "Events:"
    kubectl get events -n "$NAMESPACE" --sort-by='.lastTimestamp' | tail -20
    echo ""
    echo "--- Results: $PASSED passed, $FAILED failed ---"
    exit 1
fi
echo ""

# -- Step 4: Validate resources ----------------------------------------------
echo "--- Resource validation ---"

# Check all expected resource types exist
for kind in deployment statefulset service configmap secret serviceaccount; do
    count=$(kubectl get "$kind" -n "$NAMESPACE" -l "app.kubernetes.io/instance=$RELEASE" --no-headers 2>/dev/null | wc -l | tr -d ' ')
    if [ "$count" -gt 0 ]; then
        pass "$kind: $count resource(s) found"
    else
        # Secrets/SA might not have the label — check without label
        count_all=$(kubectl get "$kind" -n "$NAMESPACE" --no-headers 2>/dev/null | wc -l | tr -d ' ')
        if [ "$count_all" -gt 0 ]; then
            pass "$kind: $count_all resource(s) found (unlabeled)"
        else
            err "$kind: none found"
        fi
    fi
done
echo ""

# -- Step 5: Pod health ------------------------------------------------------
echo "--- Pod health ---"

# Wait for all pods to be ready
if kubectl wait --for=condition=ready pod \
    -l "app.kubernetes.io/instance=$RELEASE" \
    -n "$NAMESPACE" \
    --timeout="$TIMEOUT" 2>/dev/null; then
    pass "All pods are ready"
else
    err "Some pods are not ready"
    kubectl get pods -n "$NAMESPACE" -o wide
fi

# Check individual components
for component in app worker; do
    pod=$(kubectl get pods -n "$NAMESPACE" \
        -l "app.kubernetes.io/instance=$RELEASE,app.kubernetes.io/component=$component" \
        -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
    if [ -n "$pod" ]; then
        phase=$(kubectl get pod "$pod" -n "$NAMESPACE" -o jsonpath='{.status.phase}')
        if [ "$phase" = "Running" ]; then
            pass "$component pod ($pod) is Running"
        else
            err "$component pod ($pod) is $phase"
        fi
    else
        err "$component pod not found"
    fi
done

# Check StatefulSets (PostgreSQL, Valkey)
for sts in postgresql valkey; do
    ready=$(kubectl get statefulset -n "$NAMESPACE" \
        -l "app.kubernetes.io/instance=$RELEASE" \
        -o jsonpath="{.items[?(@.metadata.name==\"$RELEASE-mailassist-$sts\")].status.readyReplicas}" 2>/dev/null || echo "0")
    if [ "${ready:-0}" -ge 1 ]; then
        pass "$sts statefulset has $ready ready replica(s)"
    else
        # Try alternate naming
        ready=$(kubectl get statefulset -n "$NAMESPACE" \
            -o jsonpath="{.items[?(@.metadata.name==\"$RELEASE-$sts\")].status.readyReplicas}" 2>/dev/null || echo "0")
        if [ "${ready:-0}" -ge 1 ]; then
            pass "$sts statefulset has $ready ready replica(s)"
        else
            err "$sts statefulset not ready"
        fi
    fi
done
echo ""

# -- Step 6: Migration job ---------------------------------------------------
echo "--- Migration job ---"
job_status=$(kubectl get jobs -n "$NAMESPACE" \
    -l "app.kubernetes.io/component=migrate" \
    -o jsonpath='{.items[0].status.succeeded}' 2>/dev/null || echo "0")
if [ "${job_status:-0}" -ge 1 ]; then
    pass "Migration job completed successfully"
else
    warn "Migration job status: succeeded=$job_status (may have been cleaned up by TTL)"
fi
echo ""

# -- Step 7: Service connectivity --------------------------------------------
echo "--- Service connectivity ---"
svc_name=$(kubectl get svc -n "$NAMESPACE" \
    -l "app.kubernetes.io/instance=$RELEASE,app.kubernetes.io/component=app" \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)

if [ -n "$svc_name" ]; then
    pass "App service exists: $svc_name"

    # Port-forward and test /health
    kubectl port-forward "svc/$svc_name" 18080:8000 -n "$NAMESPACE" &>/dev/null &
    PF_PID=$!
    sleep 3

    if kill -0 "$PF_PID" 2>/dev/null; then
        http_code=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:18080/health 2>/dev/null || echo "000")
        if [ "$http_code" = "200" ]; then
            pass "/health returned HTTP 200"
        else
            err "/health returned HTTP $http_code"
        fi
        kill "$PF_PID" 2>/dev/null || true
        wait "$PF_PID" 2>/dev/null || true
    else
        warn "Port-forward failed — skipping HTTP health check"
    fi
else
    err "App service not found"
fi
echo ""

# -- Step 8: Upgrade test ----------------------------------------------------
echo "--- Upgrade test ---"
if helm upgrade "$RELEASE" "$CHART_DIR" \
    -f "$VALUES" \
    -n "$NAMESPACE" \
    --wait \
    --timeout "$TIMEOUT"; then
    pass "helm upgrade succeeded"
else
    err "helm upgrade failed"
fi
echo ""

# -- Summary -----------------------------------------------------------------
echo "============================================="
echo -e " Results: ${GREEN}$PASSED passed${NC}, ${RED}$FAILED failed${NC}"
echo "============================================="

[ "$FAILED" -eq 0 ] && exit 0 || exit 1
