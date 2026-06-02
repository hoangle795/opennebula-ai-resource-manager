#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════
# KB1 — CPU Overload  (tiêu chí: hoàn thành < 2 phút
#        kể từ khi Alertmanager gọi webhook)
# Requires: stress-ng  →  sudo apt install stress-ng
# ═══════════════════════════════════════════════════════
set -euo pipefail

HOST_IP="${1:-10.0.100.226}"
BACKEND="http://${HOST_IP}:8000"
STRESS_DURATION=200   # giây
POLL_TIMEOUT=210      # giây polling tối đa

RED='\033[0;31m'; GRN='\033[0;32m'; YEL='\033[1;33m'; CYN='\033[0;36m'; NC='\033[0m'

banner() { echo -e "\n${CYN}══ $* ══${NC}"; }
ok()     { echo -e "${GRN}✅ $*${NC}"; }
warn()   { echo -e "${YEL}⚠️  $*${NC}"; }
err()    { echo -e "${RED}❌ $*${NC}"; }

banner "Kịch bản 1 — CPU Overload  |  $(date '+%H:%M:%S')"

# 1. Pre-check
banner "Bước 1/5 — Kiểm tra dịch vụ"
HEALTH=$(curl -sf "${BACKEND}/health" 2>/dev/null) || { err "Backend không phản hồi: ${BACKEND}"; exit 1; }
PHASE=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin)['agent_phase'])")
ok "Backend up | Phase hiện tại: ${PHASE}"

if [[ "$PHASE" == "WAITING_APPROVAL" || "$PHASE" == "PLAN" ]]; then
    warn "Agent đang có plan chờ. Dismiss trước: curl -X POST ${BACKEND}/api/agent/approve -d '{\"action\":\"dismiss\"}'"
    exit 1
fi

# 2. Show baseline
banner "Bước 2/5 — CPU baseline"
curl -sf "${BACKEND}/api/dashboard/overview" | python3 -c "
import sys,json
d = json.load(sys.stdin)['data']['metrics']
print(f'  CPU: {d.get(\"cpu_pct\",\"N/A\")}%  |  Level: {d.get(\"cpu_level\",\"N/A\")}')
"

# 3. Start stress
banner "Bước 3/5 — Khởi động CPU stress 95% trong ${STRESS_DURATION}s"
echo "  Prometheus rule HostHighCPU: expr > 95%, for: 2m → fire sau ~2 phút"
echo "  Alertmanager group_wait: 10s → webhook gọi sau thêm 10s"
stress-ng --cpu 0 --cpu-load 95 --timeout "${STRESS_DURATION}s" --metrics-brief &
STRESS_PID=$!
echo "  stress-ng PID: ${STRESS_PID}"

# 4. Poll
banner "Bước 4/5 — Chờ AI Agent phân tích"
echo "  (poll mỗi 5s, tối đa ${POLL_TIMEOUT}s)"
START=$(date +%s)
PLAN_FOUND=0
for i in $(seq 1 $(( POLL_TIMEOUT / 5 ))); do
    sleep 5
    ELAPSED=$(( $(date +%s) - START ))
    STATE=$(curl -sf "${BACKEND}/api/agent/state" 2>/dev/null || echo '{}')
    PHASE=$(echo "$STATE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('agent_state',{}).get('current_phase','?'))" 2>/dev/null)
    CPU_NOW=$(curl -sf "${BACKEND}/api/dashboard/overview" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['metrics'].get('cpu_pct','?'))" 2>/dev/null)
    AM_LOGS=$(curl -sf "${BACKEND}/api/logs" 2>/dev/null | python3 -c "import sys,json; logs=json.load(sys.stdin); print(sum(1 for l in logs if 'Alertmanager' in str(l)))" 2>/dev/null || echo "0")
    printf "  t=%3ds | CPU: %-5s%% | Phase: %-20s | AM-logs: %s\n" "$ELAPSED" "$CPU_NOW" "$PHASE" "$AM_LOGS"

    if [[ "$PHASE" == "WAITING_APPROVAL" ]]; then
        ok "Plan ready sau ${ELAPSED}s!"
        PLAN_FOUND=1; break
    fi
done

[[ $PLAN_FOUND -eq 0 ]] && { warn "Timeout. Kiểm tra Prometheus targets và Alertmanager."; kill "$STRESS_PID" 2>/dev/null; exit 1; }

# 5. Show plan
banner "Bước 5/5 — Kế hoạch AI đề xuất"
curl -sf "${BACKEND}/api/agent/state" | python3 -c "
import sys, json
state = json.load(sys.stdin).get('agent_state', {})
print(f'  Status  : {state.get(\"analysis\",{}).get(\"status\",\"?\")}')
print(f'  Details : {state.get(\"analysis\",{}).get(\"details\",\"\")}')
print()
print('  Remediation Plan:')
for s in state.get('plan', []):
    print(f'    [{s.get(\"step\")}] {s.get(\"action\")!s:<40}  target={s.get(\"target\")}')
"
echo ""
ok "KB1 hoàn thành. Chạy ./scenario3_approve.sh để phê duyệt."
kill "$STRESS_PID" 2>/dev/null || true