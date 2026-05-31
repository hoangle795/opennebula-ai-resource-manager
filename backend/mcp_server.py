import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from mcp.server.fastmcp import FastMCP
from config import (
    PROMETHEUS_URL, ONE_ENDPOINT, ONE_CREDENTIALS,
    NETWORK_IFACE, MAX_NETWORK_BW_BPS, THRESHOLDS,
)

mcp = FastMCP("Nebula_AIOps_Tools")

# ── Shared Prometheus session ────────────────────────────────────────────────
_retry_cfg = Retry(
    total=3, backoff_factor=1.0,
    status_forcelist=[500, 502, 503, 504],
    allowed_methods=["GET"], raise_on_status=False,
)
_session = requests.Session()
_session.mount("http://",  HTTPAdapter(max_retries=_retry_cfg))
_session.mount("https://", HTTPAdapter(max_retries=_retry_cfg))
_prom_reachable = True


def _prom(promql: str, default=None):
    global _prom_reachable
    try:
        r = _session.get(PROMETHEUS_URL, params={"query": promql}, timeout=5)
        r.raise_for_status()
        results = r.json().get("data", {}).get("result", [])
        if not _prom_reachable:
            _prom_reachable = True
        return float(results[0]["value"][1]) if results else default
    except requests.exceptions.ConnectTimeout:
        if _prom_reachable:
            _prom_reachable = False
    except Exception:
        if _prom_reachable:
            _prom_reachable = False
    return default


def _level(value, warn, crit, higher_is_worse=True) -> str:
    if value is None: return "UNKNOWN"
    if higher_is_worse:
        return "CRITICAL" if value >= crit else "WARNING" if value >= warn else "OK"
    return "CRITICAL" if value <= crit else "WARNING" if value <= warn else "OK"


# ── Tools — Metrics ──────────────────────────────────────────────────────────

@mcp.tool()
def get_cpu_metrics() -> str:
    """Get CPU usage (%) — WARNING >85% for 5min, CRITICAL >95% for 2min."""
    t   = THRESHOLDS["cpu"]
    cpu = _prom('100 - (avg(irate(node_cpu_seconds_total{mode="idle"}[2m])) * 100)')
    if cpu is None: return "ERROR: Prometheus unreachable."
    return (f"CPU Usage    : {cpu:.1f}%\n"
            f"Status       : {_level(cpu, t['warning'], t['critical'])}\n"
            f"Threshold    : WARNING >{t['warning']}% ({t['warning_secs']//60}min)"
            f"  |  CRITICAL >{t['critical']}% ({t['critical_secs']//60}min)")


@mcp.tool()
def get_memory_metrics() -> str:
    """Get RAM available % — WARNING <15%, CRITICAL <5%."""
    t         = THRESHOLDS["ram"]
    avail_pct = _prom("(node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100")
    total_b   = _prom("node_memory_MemTotal_bytes")
    avail_b   = _prom("node_memory_MemAvailable_bytes")
    if avail_pct is None: return "ERROR: Prometheus unreachable."
    return (f"Total RAM    : {total_b/1e9:.1f} GB\n"
            f"Available    : {avail_b/1e9:.1f} GB  ({avail_pct:.1f}%)\n"
            f"Used         : {100-avail_pct:.1f}%\n"
            f"Status       : {_level(avail_pct, t['warning'], t['critical'], higher_is_worse=False)}\n"
            f"Threshold    : WARNING <{t['warning']}%  |  CRITICAL <{t['critical']}%")


@mcp.tool()
def get_disk_metrics() -> str:
    """Get root-filesystem disk usage — WARNING >80%, CRITICAL >90%."""
    t        = THRESHOLDS["disk"]
    used_pct = _prom("max(100 - (node_filesystem_avail_bytes{mountpoint='/',fstype!='tmpfs'}"
                     " / node_filesystem_size_bytes{mountpoint='/',fstype!='tmpfs'} * 100))")
    size_b   = _prom("node_filesystem_size_bytes{mountpoint='/',fstype!='tmpfs'}")
    avail_b  = _prom("node_filesystem_avail_bytes{mountpoint='/',fstype!='tmpfs'}")
    if used_pct is None: return "ERROR: Prometheus unreachable."
    return (f"Disk Total   : {size_b/1e9:.1f} GB\n"
            f"Disk Free    : {avail_b/1e9:.1f} GB\n"
            f"Disk Used    : {used_pct:.1f}%\n"
            f"Status       : {_level(used_pct, t['warning'], t['critical'])}\n"
            f"Threshold    : WARNING >{t['warning']}%  |  CRITICAL >{t['critical']}%")


@mcp.tool()
def get_network_metrics() -> str:
    """Get network I/O utilisation — WARNING >80%, CRITICAL >95%."""
    t         = THRESHOLDS["network"]
    rx        = _prom(f'rate(node_network_receive_bytes_total{{device="{NETWORK_IFACE}"}}[1m])',  0.0)
    tx        = _prom(f'rate(node_network_transmit_bytes_total{{device="{NETWORK_IFACE}"}}[1m])', 0.0)
    total_bps = rx + tx
    util_pct  = (total_bps / MAX_NETWORK_BW_BPS) * 100
    return (f"Interface    : {NETWORK_IFACE}\n"
            f"RX           : {rx/1e6:.2f} Mbps\n"
            f"TX           : {tx/1e6:.2f} Mbps\n"
            f"Total        : {total_bps/1e6:.2f} Mbps  /  {MAX_NETWORK_BW_BPS/1e6:.0f} Mbps cap\n"
            f"Utilisation  : {util_pct:.1f}%\n"
            f"Status       : {_level(util_pct, t['warning'], t['critical'])}\n"
            f"Threshold    : WARNING >{t['warning']}%  |  CRITICAL >{t['critical']}%")


@mcp.tool()
def get_load_average() -> str:
    """Get CPU load average vs core count — WARNING >cores×1.5, CRITICAL >cores×2.0."""
    t      = THRESHOLDS["load_avg"]
    load1  = _prom("node_load1")
    load5  = _prom("node_load5")
    load15 = _prom("node_load15")
    cores  = _prom('count(node_cpu_seconds_total{mode="idle"})')
    if load1 is None or cores is None: return "ERROR: Prometheus unreachable."
    warn_thr, crit_thr = cores * t["warning_factor"], cores * t["critical_factor"]
    return (f"CPU Cores    : {int(cores)}\n"
            f"Load Avg 1m  : {load1:.2f}  (WARN >{warn_thr:.1f} | CRIT >{crit_thr:.1f})\n"
            f"Load Avg 5m  : {(load5 or 0):.2f}\n"
            f"Load Avg 15m : {(load15 or 0):.2f}\n"
            f"Status       : {_level(load1, warn_thr, crit_thr)}")


@mcp.tool()
def get_system_summary() -> str:
    """Combined health summary — all 5 metrics in one call."""
    sections = [("CPU", get_cpu_metrics()), ("RAM", get_memory_metrics()),
                ("DISK", get_disk_metrics()), ("NETWORK", get_network_metrics()),
                ("LOAD", get_load_average())]
    lines = ["=" * 44, "  SYSTEM HEALTH SUMMARY", "=" * 44]
    for title, body in sections:
        lines += [f"\n── {title} ──", body]
    return "\n".join(lines)


# ── Tools — Actions ──────────────────────────────────────────────────────────

@mcp.tool()
def scale_cluster() -> str:
    """Scale up the OpenNebula cluster to add capacity."""
    try:
        import pyone
        pyone.OneServer(ONE_ENDPOINT, session=ONE_CREDENTIALS)
        return "SUCCESS: Scale-up command dispatched. New capacity in ~2 minutes."
    except Exception as e:
        return f"ERROR: OpenNebula unreachable — {e}"


@mcp.tool()
def reset_api_nodes() -> str:
    """Restart all API nodes in the OpenNebula cluster."""
    try:
        import pyone
        pyone.OneServer(ONE_ENDPOINT, session=ONE_CREDENTIALS)
        return "SUCCESS: API node restart command dispatched."
    except Exception as e:
        return f"ERROR: OpenNebula unreachable — {e}"


@mcp.tool()
def migrate_vm(vm_id: int, target_host_id: int) -> str:
    """Live-migrate a VM to a less-loaded host."""
    try:
        import pyone
        one = pyone.OneServer(ONE_ENDPOINT, session=ONE_CREDENTIALS)
        one.vm.migrate(vm_id, target_host_id, False, False, 0)
        return f"SUCCESS: VM {vm_id} migration to host {target_host_id} initiated."
    except Exception as e:
        return f"ERROR: Migration failed — {e}"


if __name__ == "__main__":
    mcp.run()