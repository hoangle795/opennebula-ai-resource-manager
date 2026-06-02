#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════
# KB3 — Admin phê duyệt kế hoạch (tiêu chí: thực thi thành công)
# Chạy SAU KB1 hoặc KB2 khi agent đang ở WAITING_APPROVAL
# ═══════════════════════════════════════════════════════
set -euo pipefail

HOST_IP="${1:-10.0.100.226}"
BACKEND="http://${HOST_IP}:8000"

GRN='\033[0;32m'; YEL='\033[1;33m'; CYN='\033[0;36m'; NC='\033[0m'
banner() { echo -e "\n${CYN}══ $* ══${NC}"; }
ok()     { echo -e "${GRN}✅ $*${NC}"; }
warn()   { echo -e "${YEL}⚠️  $*${NC}"; }

banner "Kịch bản 3 — Admin Approve Plan  |  $(date '+%H:%M:%S')"

# 1. Kiểm tra phase
banner "Bước 1/4 — Kiểm tra trạng thái Agent"
STATE=$(curl -sf "${BACKEND}/api/agent/state")
PHASE=$(echo "$STATE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('agent_state',{}).get('current_phase','?'))")
echo "  Phase hiện tại: ${PHASE}"

if [[ "$PHASE" != "WAITING_APPROVAL" ]]; then
    warn "Agent không ở WAITING_APPROVAL (đang: ${PHASE})."
    warn "Hãy chạy KB1 hoặc KB2 trước."
    exit 1
fi
ok "Agent đang chờ phê duyệt."

# 2. Hiển thị kế hoạch
banner "Bước 2/4 — Kế hoạch AI cần phê duyệt"
echo "$STATE" | python3 -c "
import sys, json
state = json.load(sys.stdin).get('agent_state', {})
analysis = state.get('analysis', {})
print(f'  Status  : {analysis.get(\"status\", \"?\")}')
print(f'  Details : {analysis.get(\"details\", \"\")}')
print()
alerts = state.get('alerts', [])
if alerts:
    print('  Active Alerts:')
    for a in alerts:
        print(f'    [{a.get(\"level\",\"?\")}] {a.get(\"metric\",\"\").upper()}: {a.get(\"message\",\"\")}')
    print()
plan = state.get('plan', [])
print(f'  Remediation Plan ({len(plan)} bước):')
for s in plan:
    print(f'    Step {s.get(\"step\")}: {s.get(\"action\")!s}')
    print(f'            Target: {s.get(\"target\")}')
"

# 3. Xác nhận phê duyệt
banner "Bước 3/4 — Gửi lệnh Approve"
echo "  Gọi: POST ${BACKEND}/api/agent/approve  {action: approve}"
echo ""
RESP=$(curl -sf -X POST "${BACKEND}/api/agent/approve" \
    -H "Content-Type: application/json" \
    -d '{"action": "approve"}')
echo "  Response: ${RESP}"

# 4. Xác nhận kết quả
banner "Bước 4/4 — Xác nhận thực thi"
sleep 4
NEW_STATE=$(curl -sf "${BACKEND}/api/agent/state")
NEW_PHASE=$(echo "$NEW_STATE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('agent_state',{}).get('current_phase','?'))")
EXEC_STATUS=$(echo "$NEW_STATE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('agent_state',{}).get('execute_status','?'))")
echo "  Phase mới    : ${NEW_PHASE}"
echo "  Exec status  : ${EXEC_STATUS}"

echo ""
echo "  Logs gần nhất:"
curl -sf "${BACKEND}/api/logs" | python3 -c "
import sys, json
logs = json.load(sys.stdin)
for l in logs[:6]:
    print(f'    [{l[3]}] [{l[1]}] {l[2]}')
"
echo ""
ok "KB3 hoàn thành."
echo "  Web App: http://${HOST_IP}:8000/agent"
echo "  Logs   : http://${HOST_IP}:8000/system-logs"