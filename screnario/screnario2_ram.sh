#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════
# KB2 — RAM Shortage  (tiêu chí: đề xuất đúng và khả thi)
# Cách 1 (stress-ng): sudo apt install stress-ng
# Cách 2 (Python):    không cần cài thêm
# ═══════════════════════════════════════════════════════
set -euo pipefail

HOST_IP="${1:-10.0.100.226}"
BACKEND="http://${HOST_IP}:8000"
METHOD="${2:-python}"   # "stress" hoặc "python"
POLL_TIMEOUT=360

RED='\033[0;31m'; GRN='\033[0;32m'; YEL='\033[1;33m'; CYN='\033[0;36m'; NC='\033[0m'
banner() { echo -e "\n${CYN}══ $* ══${NC}"; }
ok()     { echo -e "${GRN}✅ $*${NC}"; }
warn()   { echo -e "${YEL}⚠️  $*${NC}"; }

banner "Kịch bản 2 — RAM Shortage  |  $(date '+%H:%M:%S')"

# 1. Pre-check
banner "Bước 1/5 — Kiểm tra dịch vụ & RAM hiện tại"
curl -sf "${BACKEND}/health" > /dev/null || { echo "❌ Backend không phản hồi"; exit 1; }

TOTAL_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
AVAIL_KB=$(grep MemAvailable /proc/meminfo | awk '{print $2}')
TOTAL_MB=$(( TOTAL_KB / 1024 ))
AVAIL_PCT=$(( AVAIL_KB * 100 / TOTAL_KB ))
echo "  Total RAM : ${TOTAL_MB}MB"
echo "  Available : ${AVAIL_PCT}%  ($(( AVAIL_KB / 1024 ))MB)"
echo ""
echo "  Mục tiêu  : đẩy Available xuống < 15% (WARNING) hoặc < 5% (CRITICAL)"

# 2. Calculate alloc
# Để đạt <15% avail: cần chiếm > 85% tổng RAM
# Giữ lại 8% buffer để tránh OOM-killer
TARGET_FILL_PCT=88
ALLOC_MB=$(( TOTAL_MB * TARGET_FILL_PCT / 100 ))
echo "  Sẽ chiếm  : ${ALLOC_MB}MB (${TARGET_FILL_PCT}% RAM)"

PHASE=$(curl -sf "${BACKEND}/api/agent/state" | python3 -c "import sys,json; print(json.load(sys.stdin).get('agent_state',{}).get('current_phase','?'))")
if [[ "$PHASE" == "WAITING_APPROVAL" ]]; then
    warn "Agent đang có plan chờ. Dismiss trước."; exit 1
fi

# 3. Start RAM stress
banner "Bước 3/5 — Chiếm ${ALLOC_MB}MB RAM trong 5 phút"
echo "  Prometheus rule HostMemoryWarning: avail < 15%, for: 2m"
echo "  Prometheus rule HostLowMemory    : avail < 5%,  for: 1m"

if [[ "$METHOD" == "stress" ]]; then
    echo "  Method: stress-ng"
    stress-ng --vm 1 --vm-bytes "${ALLOC_MB}M" --vm-keep --timeout 300s &
    STRESS_PID=$!
else
    echo "  Method: Python (không cần cài thêm)"
    python3 - << PYEOF &
import time, sys
ALLOC_MB = ${ALLOC_MB}
print(f"  Allocating {ALLOC_MB}MB...", flush=True)
buf = bytearray(ALLOC_MB * 1024 * 1024)
print("  Done. Sleeping 300s...", flush=True)
time.sleep(300)
PYEOF
    STRESS_PID=$!
fi
echo "  PID: ${STRESS_PID}"

sleep 3
AVAIL_NOW=$(grep MemAvailable /proc/meminfo | awk '{print $2}')
AVAIL_NOW_PCT=$(( AVAIL_NOW * 100 / TOTAL_KB ))
echo "  RAM available ngay sau stress: ${AVAIL_NOW_PCT}%"

# 4. Poll
banner "Bước 4/5 — Chờ AI Agent phân tích (tối đa ${POLL_TIMEOUT}s)"
START=$(date +%s)
PLAN_FOUND=0
for i in $(seq 1 $(( POLL_TIMEOUT / 5 ))); do
    sleep 5
    ELAPSED=$(( $(date +%s) - START ))
    AVAIL_KB_NOW=$(grep MemAvailable /proc/meminfo | awk '{print $2}')
    AVAIL_NOW=$(( AVAIL_KB_NOW * 100 / TOTAL_KB ))
    STATE=$(curl -sf "${BACKEND}/api/agent/state" 2>/dev/null || echo '{}')
    PHASE=$(echo "$STATE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('agent_state',{}).get('current_phase','?'))" 2>/dev/null)
    AM_LOGS=$(curl -sf "${BACKEND}/api/logs" 2>/dev/null | python3 -c "import sys,json; logs=json.load(sys.stdin); print(sum(1 for l in logs if 'Memory' in str(l) or 'RAM' in str(l) or 'Alertmanager' in str(l)))" 2>/dev/null || echo 0)
    printf "  t=%3ds | RAM avail: %3d%% | Phase: %-20s | relevant-logs: %s\n" "$ELAPSED" "$AVAIL_NOW" "$PHASE" "$AM_LOGS"

    if [[ "$PHASE" == "WAITING_APPROVAL" ]]; then
        ok "Plan ready sau ${ELAPSED}s!"
        PLAN_FOUND=1; break
    fi
done

[[ $PLAN_FOUND -eq 0 ]] && { warn "Timeout. Kiểm tra Prometheus."; kill "$STRESS_PID" 2>/dev/null; exit 1; }

# 5. Show plan
banner "Bước 5/5 — Kế hoạch AI đề xuất"
curl -sf "${BACKEND}/api/agent/state" | python3 -c "
import sys, json
state = json.load(sys.stdin).get('agent_state', {})
alerts = state.get('alerts', [])
print('  Active Alerts:')
for a in alerts:
    print(f'    [{a.get(\"level\")}] {a.get(\"metric\",\"\").upper()}: {a.get(\"message\",\"\")}')
print()
print('  Remediation Plan:')
for s in state.get('plan', []):
    print(f'    [{s.get(\"step\")}] {s.get(\"action\")!s:<40}  target={s.get(\"target\")}')
"
ok "KB2 hoàn thành. Chạy ./scenario3_approve.sh để phê duyệt."
kill "$STRESS_PID" 2>/dev/null || true