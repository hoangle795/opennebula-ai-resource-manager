import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from fastapi import APIRouter
from config import (
    PROMETHEUS_URL, ONE_ENDPOINT, ONE_CREDENTIALS,
    NETWORK_IFACE, MAX_NETWORK_BW_BPS, THRESHOLDS,
)

router = APIRouter()

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
    except (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError):
        if _prom_reachable:
            _prom_reachable = False
    except Exception:
        pass
    return default


def _level(value, warn, crit, higher_is_worse=True) -> str:
    if value is None: return "N/A"
    if higher_is_worse:
        return "CRITICAL" if value >= crit else "WARNING" if value >= warn else "OK"
    return "CRITICAL" if value <= crit else "WARNING" if value <= warn else "OK"


@router.get("/overview")
async def get_dashboard_overview():
    # CPU
    cpu_pct   = _prom('100 - (avg(irate(node_cpu_seconds_total{mode="idle"}[2m])) * 100)')
    cpu_cores = _prom('count(node_cpu_seconds_total{mode="idle"})')

    # RAM
    ram_avail_pct = _prom("(node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100")
    ram_total_b   = _prom("node_memory_MemTotal_bytes")
    ram_avail_b   = _prom("node_memory_MemAvailable_bytes")

    # Disk
    disk_used_pct = _prom("max(100 - (node_filesystem_avail_bytes{mountpoint='/',fstype!='tmpfs'}"
                          " / node_filesystem_size_bytes{mountpoint='/',fstype!='tmpfs'} * 100))")
    disk_total_b  = _prom("node_filesystem_size_bytes{mountpoint='/',fstype!='tmpfs'}")
    disk_avail_b  = _prom("node_filesystem_avail_bytes{mountpoint='/',fstype!='tmpfs'}")

    # Network — sum tất cả interface, bỏ loopback (giống ai_worker)
    rx_bps       = _prom('sum(rate(node_network_receive_bytes_total{device!="lo"}[1m]))',  0.0)
    tx_bps       = _prom('sum(rate(node_network_transmit_bytes_total{device!="lo"}[1m]))', 0.0)
    net_util_pct = ((rx_bps + tx_bps) / MAX_NETWORK_BW_BPS) * 100

    # Load Average
    load1  = _prom("node_load1")
    load5  = _prom("node_load5")
    load15 = _prom("node_load15")
    la_thr = THRESHOLDS["load_avg"]
    load_level = (
        _level(load1 / cpu_cores, la_thr["warning_factor"], la_thr["critical_factor"])
        if load1 is not None and cpu_cores else "N/A"
    )

    # OpenNebula
    nodes, total_vms = [], 0
    try:
        import pyone
        one      = pyone.OneServer(ONE_ENDPOINT, session=ONE_CREDENTIALS)
        vmpool   = one.vmpool.info(-1, -1, -1, -1)
        if hasattr(vmpool, "VM") and vmpool.VM:
            vm_list   = vmpool.VM if isinstance(vmpool.VM, list) else [vmpool.VM]
            total_vms = len(vm_list)
        hostpool = one.hostpool.info()
        if hasattr(hostpool, "HOST") and hostpool.HOST:
            for h in (hostpool.HOST if isinstance(hostpool.HOST, list) else [hostpool.HOST]):
                nodes.append({"ip": h.NAME, "status": "ACTIVE" if h.STATE == 2 else "WARNING"})
    except Exception as exc:
        nodes.append({"ip": f"OpenNebula error: {str(exc)[:80]}", "status": "ERROR"})

    c_thr, r_thr, d_thr, n_thr = (
        THRESHOLDS["cpu"], THRESHOLDS["ram"], THRESHOLDS["disk"], THRESHOLDS["network"]
    )

    return {
        "status": "success",
        "data": {
            "metrics": {
                "cpu_pct":       round(cpu_pct, 1)        if cpu_pct        is not None else None,
                "cpu_level":     _level(cpu_pct, c_thr["warning"], c_thr["critical"]),
                "cpu_cores":     int(cpu_cores)            if cpu_cores      else None,
                "ram_avail_pct": round(ram_avail_pct, 1)  if ram_avail_pct  is not None else None,
                "ram_used_pct":  round(100-ram_avail_pct,1) if ram_avail_pct is not None else None,
                "ram_total_gb":  round(ram_total_b/1e9,1) if ram_total_b    else None,
                "ram_avail_gb":  round(ram_avail_b/1e9,1) if ram_avail_b    else None,
                "ram_level":     _level(ram_avail_pct, r_thr["warning"], r_thr["critical"], higher_is_worse=False),
                "disk_used_pct": round(disk_used_pct, 1)  if disk_used_pct  is not None else None,
                "disk_total_gb": round(disk_total_b/1e9,1) if disk_total_b  else None,
                "disk_avail_gb": round(disk_avail_b/1e9,1) if disk_avail_b  else None,
                "disk_level":    _level(disk_used_pct, d_thr["warning"], d_thr["critical"]),
                "net_rx_mbps":   round(rx_bps * 8 / 1e6, 2),   # bytes/s → Mbps
                "net_tx_mbps":   round(tx_bps * 8 / 1e6, 2),   # bytes/s → Mbps
                "net_util_pct":  round(net_util_pct, 1),
                "net_level":     _level(net_util_pct, n_thr["warning"], n_thr["critical"]),
                "load1":         round(load1,  2) if load1  is not None else None,
                "load5":         round(load5,  2) if load5  is not None else None,
                "load15":        round(load15, 2) if load15 is not None else None,
                "load_level":    load_level,
                "total_instances": total_vms,
                "prometheus_ok": _prom_reachable,
            },
            "alerts": [],
            "nodes":  nodes,
        },
    }