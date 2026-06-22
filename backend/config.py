import os
from dotenv import load_dotenv

load_dotenv()
# ── Infrastructure ─────────────────────────────────────────────────────────
PROMETHEUS_URL  = os.getenv("PROMETHEUS_URL",  "http://192.168.57.7:9090/api/v1/query")
ONE_ENDPOINT    = os.getenv("ONE_ENDPOINT",    "http://192.168.57.7:2633/RPC2")
ONE_CREDENTIALS = os.getenv("ONE_CREDENTIALS", "oneadmin:SlJPy7mFEa")
GROQ_API_KEY    = os.getenv("GROQ_API_KEY",    "")  

# ── Network ────────────────────────────────────────────────────────────────
NETWORK_IFACE      = os.getenv("NETWORK_IFACE",       "eth0")
MAX_NETWORK_BW_BPS = int(os.getenv("MAX_NETWORK_BW_BPS", str(1_000_000_000)))  # 1 Gbps

# ── Monitoring loop interval (seconds) ────────────────────────────────────
MONITOR_INTERVAL = int(os.getenv("MONITOR_INTERVAL", "30"))

# ── SSH — dùng cho process_tools.py (xem top process + kill process) ───────
# Đây phải là máy đang được Prometheus giám sát (host chạy node_exporter),
# KHÔNG phải máy chạy backend FastAPI.
# IP 192.168.57.9 = host-node thực tế (nơi chạy stress-ng demo + node_exporter)
TARGET_HOST         = os.getenv("TARGET_HOST",         "192.168.57.9")
TARGET_SSH_USER     = os.getenv("TARGET_SSH_USER",     "")   # đặt trong .env
TARGET_SSH_PASSWORD = os.getenv("TARGET_SSH_PASSWORD", "")   # đặt trong .env, KHÔNG hardcode
TARGET_SSH_PORT     = int(os.getenv("TARGET_SSH_PORT", "22"))
TARGET_SSH_KEY_PATH = os.getenv("TARGET_SSH_KEY_PATH", "")   # nếu dùng SSH key thay password

# ── Alert thresholds ───────────────────────────────────────────────────────
#
#  Metric            Source          WARNING             CRITICAL
#  ─────────────────────────────────────────────────────────────────────────
#  CPU Usage (%)     Node Exporter   >85% for 5 min      >95% for 2 min
#  RAM Available     Node Exporter   <15% total RAM       <5% total RAM
#  Disk Usage (%)    Node Exporter   >80% capacity       >90% capacity
#  Network I/O       Node Exporter   >80% bandwidth      >95% bandwidth
#  CPU Load Avg      Node Exporter   >cores × 1.5        >cores × 2.0
#
THRESHOLDS = {
    "cpu": {
        "warning":        85.0,   # %
        "critical":       95.0,   # %
        "warning_secs":  300,     # must be sustained 5 minutes
        "critical_secs": 120,     # must be sustained 2 minutes
    },
    "ram": {                      # available % — low = bad
        "warning":  15.0,
        "critical":  5.0,
    },
    "disk": {                     # used % — high = bad
        "warning":  80.0,
        "critical": 90.0,
    },
    "network": {                  # utilisation % — high = bad
        "warning":  80.0,
        "critical": 95.0,
    },
    "load_avg": {                 # load1 compared to core count
        "warning_factor":  1.5,
        "critical_factor": 2.0,
    },
}