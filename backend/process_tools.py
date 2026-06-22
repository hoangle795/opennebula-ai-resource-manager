"""
process_tools.py
─────────────────
SSH vào host đang bị giám sát (TARGET_HOST trong config.py) để:
  1. Lấy danh sách process đang ăn CPU/RAM nhiều nhất (get_top_processes)
  2. Kill 1 process theo PID hoặc tên (kill_process)

Lý do cần SSH: Prometheus Node Exporter KHÔNG có per-process metrics
(chỉ có tổng CPU/RAM toàn hệ thống), nên muốn biết "process nào" đang
gây tăng cao thì phải hỏi trực tiếp OS qua SSH.

TARGET_HOST = 192.168.57.9 (host-node thực tế, nơi chạy stress-ng demo)
"""

import paramiko
from database import add_log
from config import (
    TARGET_HOST, TARGET_SSH_USER, TARGET_SSH_PASSWORD,
    TARGET_SSH_PORT, TARGET_SSH_KEY_PATH,
)

# ── Danh sách process KHÔNG ĐƯỢC kill (bảo vệ hệ thống) ─────────────────────
_PROTECTED_NAMES = {
    "systemd", "init", "kthreadd", "sshd", "dockerd", "containerd",
    "node_exporter", "prometheus", "alertmanager", "grafana-server",
    "kernel", "kworker", "bash", "login", "cron", "rsyslogd",
    "NetworkManager", "systemd-journald", "systemd-logind", "dbus-daemon",
}
_PROTECTED_PIDS = {0, 1}


def _ssh_connect():
    """Mở 1 kết nối SSH tới TARGET_HOST. Ưu tiên SSH key, fallback password."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    if TARGET_SSH_KEY_PATH:
        client.connect(
            hostname=TARGET_HOST,
            port=TARGET_SSH_PORT,
            username=TARGET_SSH_USER,
            key_filename=TARGET_SSH_KEY_PATH,
            timeout=5,
        )
    else:
        client.connect(
            hostname=TARGET_HOST,
            port=TARGET_SSH_PORT,
            username=TARGET_SSH_USER,
            password=TARGET_SSH_PASSWORD,
            timeout=5,
        )
    return client


def _run_remote(cmd: str) -> tuple[str, str]:
    """Chạy lệnh trên host qua SSH, trả về (stdout, stderr)."""
    client = _ssh_connect()
    try:
        stdin, stdout, stderr = client.exec_command(cmd, timeout=8)
        out = stdout.read().decode(errors="ignore").strip()
        err = stderr.read().decode(errors="ignore").strip()
        return out, err
    finally:
        client.close()


def get_top_processes(limit: int = 8) -> str:
    """
    Lấy top N process đang ăn CPU cao nhất trên TARGET_HOST.
    Trả về text format dễ đọc cho LLM, bao gồm PID, %CPU, %MEM, tên lệnh.
    """
    cmd = f"ps -eo pid,comm,pcpu,pmem,etimes --sort=-pcpu | head -n {limit + 1}"
    try:
        out, err = _run_remote(cmd)
        if err and not out:
            return f"ERROR: Không thể chạy ps trên {TARGET_HOST}: {err}"

        lines = out.strip().split("\n")
        if len(lines) < 2:
            return "ERROR: Không lấy được dữ liệu process."

        header = lines[0]
        rows = lines[1:]

        result = [f"=== TOP {len(rows)} PROCESS ĂN CPU NHIỀU NHẤT trên {TARGET_HOST} ===", header]
        for row in rows:
            parts = row.split(None, 4)
            if len(parts) < 5:
                result.append(row)
                continue
            pid, comm, pcpu, pmem, etimes = parts
            protected = " ⚠️ [PROTECTED — không thể kill]" if (
                comm in _PROTECTED_NAMES or int(pid) in _PROTECTED_PIDS
            ) else ""
            result.append(f"PID={pid:<7} CMD={comm:<20} CPU={pcpu}% MEM={pmem}% UPTIME={etimes}s{protected}")

        return "\n".join(result)

    except Exception as exc:
        add_log("ERROR", f"[process_tools] SSH lỗi khi lấy top process: {exc}")
        return f"ERROR: Không kết nối được SSH tới {TARGET_HOST}: {exc}"


def kill_process(pid: int = None, name: str = None, confirm: bool = False) -> str:
    """
    Kill process theo PID hoặc tên (ưu tiên PID nếu có cả 2).
    BẮT BUỘC confirm=True mới thực thi — đây là rào chắn an toàn cuối cùng,
    LLM chỉ được set confirm=True khi user đã xác nhận rõ ràng trong chat.
    """
    if not confirm:
        return (
            "BLOCKED: Cần xác nhận tường minh từ admin trước khi kill. "
            "Hãy hỏi lại admin: 'Bạn xác nhận muốn kill process này?' "
            "rồi gọi lại tool này với confirm=true."
        )

    if not pid and not name:
        return "ERROR: Cần cung cấp pid hoặc name để kill process."

    try:
        # ── Bước 1: xác định PID + tên thật từ hệ thống (chống giả mạo tên) ──
        if pid:
            check_cmd = f"ps -p {pid} -o comm= "
        else:
            check_cmd = f"pgrep -x {name} | head -1"

        out, err = _run_remote(check_cmd)
        if not out:
            return f"ERROR: Không tìm thấy process {'PID='+str(pid) if pid else 'name='+name} đang chạy."

        if pid:
            real_pid = pid
            real_name = out.strip()
        else:
            real_pid = int(out.strip())
            name_out, _ = _run_remote(f"ps -p {real_pid} -o comm=")
            real_name = name_out.strip()

        # ── Bước 2: kiểm tra protected list ──────────────────────────────────
        if real_pid in _PROTECTED_PIDS or real_name in _PROTECTED_NAMES:
            add_log("WARN", f"[process_tools] Chặn kill process bảo vệ: PID={real_pid} ({real_name})")
            return (
                f"REFUSED: PID {real_pid} ({real_name}) là process hệ thống quan trọng. "
                "Không được phép kill để tránh sập hệ thống."
            )

        # ── Bước 3: thực thi kill thật ────────────────────────────────────────
        kill_out, kill_err = _run_remote(f"kill -9 {real_pid}")
        if kill_err:
            add_log("ERROR", f"[process_tools] Kill PID {real_pid} thất bại: {kill_err}")
            return f"ERROR: Kill PID {real_pid} ({real_name}) thất bại: {kill_err}"

        add_log("SUCCESS", f"[process_tools] Đã kill PID {real_pid} ({real_name}) theo xác nhận admin.")
        return f"SUCCESS: Đã kill PID {real_pid} ({real_name}). Hệ thống sẽ tự cập nhật CPU trong vài giây."

    except Exception as exc:
        add_log("ERROR", f"[process_tools] Lỗi khi kill process: {exc}")
        return f"ERROR: Không thể kill process — {exc}"