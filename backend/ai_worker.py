import os
import time
import json
import threading
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime
from typing import Optional

from database import add_log
from config import (
    PROMETHEUS_URL, THRESHOLDS, MONITOR_INTERVAL,
    NETWORK_IFACE, MAX_NETWORK_BW_BPS, GROQ_API_KEY,
)

os.environ.setdefault("GROQ_API_KEY", GROQ_API_KEY)

# ── Shared Prometheus session (timeout 5s, retry 3 lần, không spam log) ──────
_retry_cfg = Retry(
    total=3, backoff_factor=1.0,
    status_forcelist=[500, 502, 503, 504],
    allowed_methods=["GET"], raise_on_status=False,
)
_prom_session = requests.Session()
_prom_session.mount("http://",  HTTPAdapter(max_retries=_retry_cfg))
_prom_session.mount("https://", HTTPAdapter(max_retries=_retry_cfg))
_prom_reachable = True   


class MetricSnapshot:
    __slots__ = (
        "cpu_pct", "ram_avail_pct", "disk_used_pct",
        "net_util_pct", "load1", "cpu_cores", "timestamp",
        "rx_mbps", "tx_mbps",  
    )
    def __init__(self):
        self.cpu_pct        = 0.0
        self.ram_avail_pct  = 100.0
        self.disk_used_pct  = 0.0
        self.net_util_pct   = 0.0
        self.load1          = 0.0
        self.cpu_cores      = 1
        self.timestamp      = datetime.now()
        self.rx_mbps        = 0.0  
        self.tx_mbps        = 0.0 


class AIAgentWorker:

    def __init__(self):
        self.is_running      = False
        self.autonomous_mode = False
        self._demo_spike     = False
        self._cpu_warn_since: Optional[datetime] = None
        self._cpu_crit_since: Optional[datetime] = None
        self.state = {
            "current_phase": "MONITOR",
            "metrics": {
                "cpu": 0.0, "ram_avail_pct": 100.0,
                "disk_used_pct": 0.0, "net_util_pct": 0.0,
                "load1": 0.0, "cpu_cores": 1,
                "rx": 0.0, "tx": 0.0, 
            },
            "alerts":  [],
            "analysis": {
                "confidence": 99.9, "status": "System Healthy",
                "details": "All metrics within normal thresholds.",
            },
            "plan": [], "execute_status": "Idle",
        }

    def trigger_anomaly(self):
        self._demo_spike = True
        add_log("WARN", "Demo anomaly triggered — simulating CPU spike to 95.8%.")

    def reset_anomaly(self):
        self._demo_spike = False
        add_log("INFO", "Demo anomaly cleared manually.")

    # ── Prometheus helper ────────────────────────────────────────────────────
    def _prom(self, promql: str, default=None):
        global _prom_reachable
        try:
            r = _prom_session.get(
                PROMETHEUS_URL, params={"query": promql}, timeout=5 
            )
            r.raise_for_status()
            results = r.json().get("data", {}).get("result", [])
            if not _prom_reachable:
                _prom_reachable = True
                add_log("INFO", "Prometheus connection restored.")
            return float(results[0]["value"][1]) if results else default
        except requests.exceptions.ConnectTimeout:
            self._prom_error("ConnectTimeout", promql)
        except requests.exceptions.ConnectionError as e:
            self._prom_error(f"ConnectionError: {e}", promql)
        except Exception as e:
            self._prom_error(str(e), promql)
        return default

    def _prom_error(self, reason: str, promql: str):
        global _prom_reachable
        if _prom_reachable:        
            _prom_reachable = False
            add_log("ERROR", f"Prometheus unreachable ({reason}). Query: [{promql[:60]}]")

    # ── Metric collection ────────────────────────────────────────────────────
    def _collect(self) -> MetricSnapshot:
        snap = MetricSnapshot()
        snap.cpu_pct = (
            95.8 if self._demo_spike else
            self._prom('100 - (avg(irate(node_cpu_seconds_total{mode="idle"}[2m])) * 100)', 0.0)
        )
        snap.ram_avail_pct = self._prom(
            "(node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100", 100.0)
        snap.disk_used_pct = self._prom(
            "max(100 - (node_filesystem_avail_bytes{mountpoint='/',fstype!='tmpfs'}"
            " / node_filesystem_size_bytes{mountpoint='/',fstype!='tmpfs'} * 100))", 0.0)
       # Tự động tính tổng (sum) tất cả các card mạng, bỏ qua card ảo device!="lo"
        rx = self._prom('sum(rate(node_network_receive_bytes_total{device!="lo"}[1m]))', 0.0)
        tx = self._prom('sum(rate(node_network_transmit_bytes_total{device!="lo"}[1m]))', 0.0)
        
        # Đã đổi Bytes/s sang Mbps và lưu vào state
        snap.rx_mbps = (rx * 8) / 1_000_000
        snap.tx_mbps = (tx * 8) / 1_000_000
        
        snap.net_util_pct = (((rx + tx) * 8) / MAX_NETWORK_BW_BPS) * 100
        snap.cpu_cores = int(self._prom('count(node_cpu_seconds_total{mode="idle"})', 1))
        snap.load1     = self._prom("node_load1", 0.0)
        return snap

    # ── Threshold evaluation ─────────────────────────────────────────────────
    def _evaluate(self, snap: MetricSnapshot) -> list:
        alerts = []
        now, thr = datetime.now(), THRESHOLDS

        # CPU (time-based)
        c = thr["cpu"]
        if snap.cpu_pct >= c["warning"]:
            if self._cpu_warn_since is None: self._cpu_warn_since = now
            if snap.cpu_pct >= c["critical"]:
                if self._cpu_crit_since is None: self._cpu_crit_since = now
                elapsed = (now - self._cpu_crit_since).total_seconds()
                if elapsed >= c["critical_secs"]:
                    alerts.append({"metric":"cpu","level":"CRITICAL","value":f"{snap.cpu_pct:.1f}%",
                        "message":f"CPU {snap.cpu_pct:.1f}% for >{c['critical_secs']//60}min (CRITICAL)"})
                else:
                    alerts.append({"metric":"cpu","level":"WARNING","value":f"{snap.cpu_pct:.1f}%",
                        "message":f"CPU {snap.cpu_pct:.1f}% — CRITICAL in {int(c['critical_secs']-elapsed)}s"})
            else:
                self._cpu_crit_since = None
                if (now - self._cpu_warn_since).total_seconds() >= c["warning_secs"]:
                    alerts.append({"metric":"cpu","level":"WARNING","value":f"{snap.cpu_pct:.1f}%",
                        "message":f"CPU {snap.cpu_pct:.1f}% for >{c['warning_secs']//60}min (WARNING)"})
        else:
            self._cpu_warn_since = self._cpu_crit_since = None

        # RAM
        r = thr["ram"]
        if snap.ram_avail_pct <= r["critical"]:
            alerts.append({"metric":"ram","level":"CRITICAL","value":f"{snap.ram_avail_pct:.1f}%",
                "message":f"RAM only {snap.ram_avail_pct:.1f}% free (CRITICAL <{r['critical']}%)"})
        elif snap.ram_avail_pct <= r["warning"]:
            alerts.append({"metric":"ram","level":"WARNING","value":f"{snap.ram_avail_pct:.1f}%",
                "message":f"RAM low {snap.ram_avail_pct:.1f}% free (WARNING <{r['warning']}%)"})

        # Disk
        d = thr["disk"]
        if snap.disk_used_pct >= d["critical"]:
            alerts.append({"metric":"disk","level":"CRITICAL","value":f"{snap.disk_used_pct:.1f}%",
                "message":f"Disk {snap.disk_used_pct:.1f}% full (CRITICAL >{d['critical']}%)"})
        elif snap.disk_used_pct >= d["warning"]:
            alerts.append({"metric":"disk","level":"WARNING","value":f"{snap.disk_used_pct:.1f}%",
                "message":f"Disk {snap.disk_used_pct:.1f}% full (WARNING >{d['warning']}%)"})

        # Network
        n = thr["network"]
        if snap.net_util_pct >= n["critical"]:
            alerts.append({"metric":"network","level":"CRITICAL","value":f"{snap.net_util_pct:.1f}%",
                "message":f"Network {snap.net_util_pct:.1f}% saturated (CRITICAL >{n['critical']}%)"})
        elif snap.net_util_pct >= n["warning"]:
            alerts.append({"metric":"network","level":"WARNING","value":f"{snap.net_util_pct:.1f}%",
                "message":f"Network {snap.net_util_pct:.1f}% utilised (WARNING >{n['warning']}%)"})

        # Load Average
        la = thr["load_avg"]
        warn_load, crit_load = snap.cpu_cores * la["warning_factor"], snap.cpu_cores * la["critical_factor"]
        if snap.load1 >= crit_load:
            alerts.append({"metric":"load_avg","level":"CRITICAL","value":f"{snap.load1:.2f}",
                "message":f"Load {snap.load1:.2f} > {crit_load:.1f} (cores×{la['critical_factor']})"})
        elif snap.load1 >= warn_load:
            alerts.append({"metric":"load_avg","level":"WARNING","value":f"{snap.load1:.2f}",
                "message":f"Load {snap.load1:.2f} > {warn_load:.1f} (cores×{la['warning_factor']})"})

        return alerts

    # ── MAPE-K loop ──────────────────────────────────────────────────────────
    def mape_k_loop(self):
        self.is_running = True
        add_log("INFO", "MAPE-K loop started — monitoring 5 metrics.")
        while self.is_running:
            if self.state.get("current_phase") == "WAITING_APPROVAL":
                time.sleep(1)
                continue

            self.state["current_phase"] = "MONITOR"
            snap = self._collect()
            
            # Đã thêm rx, tx vào dict để cập nhật state
            self.state["metrics"].update({
                "cpu": snap.cpu_pct, "ram_avail_pct": snap.ram_avail_pct,
                "disk_used_pct": snap.disk_used_pct, "net_util_pct": snap.net_util_pct,
                "load1": snap.load1, "cpu_cores": snap.cpu_cores,
                "rx": snap.rx_mbps, "tx": snap.tx_mbps, 
            })
            time.sleep(2)

            self.state["current_phase"] = "ANALYZE"
            alerts   = self._evaluate(snap)
            self.state["alerts"] = alerts
            critical = [a for a in alerts if a["level"] == "CRITICAL"]
            warnings = [a for a in alerts if a["level"] == "WARNING"]

            if critical:
                summary = "; ".join(a["message"] for a in critical)
                self.state["analysis"] = {"confidence": 98.5, "status": "CRITICAL", "details": summary}
                add_log("ERROR", f"CRITICAL: {summary}")
                self._plan_and_wait(snap, critical)
            elif warnings:
                summary = "; ".join(a["message"] for a in warnings)
                self.state["analysis"] = {"confidence": 95.0, "status": "WARNING", "details": summary}
                add_log("WARN", f"Warning: {summary}")
                time.sleep(MONITOR_INTERVAL)
            else:
                self.state["analysis"] = {"confidence": 99.9, "status": "System Healthy",
                    "details": "All metrics within normal thresholds."}
                time.sleep(MONITOR_INTERVAL)

    # ── Plan ─────────────────────────────────────────────────────────────────
    def _plan_and_wait(self, snap: MetricSnapshot, alerts: list):
        self.state["current_phase"] = "PLAN"
        add_log("INFO", "Invoking Llama-3 AI to generate remediation plan…")
        try:
            from crewai import Agent, Task, Crew, Process, LLM
            alert_block   = "\n".join(f"  [{a['level']}] {a['metric'].upper()}: {a['message']}" for a in alerts)
            metrics_block = (f"CPU={snap.cpu_pct:.1f}% RAM_avail={snap.ram_avail_pct:.1f}% "
                             f"Disk={snap.disk_used_pct:.1f}% Net={snap.net_util_pct:.1f}% "
                             f"Load={snap.load1:.2f}/{snap.cpu_cores}cores")
            llm = LLM(model="groq/llama-3.3-70b-versatile", api_key=os.getenv("GROQ_API_KEY"), temperature=0.0, max_tokens=500)
            agent = Agent(role="Remediation Architect",
                goal="Produce exactly 3 concrete remediation steps as JSON.",
                backstory="Senior SRE for OpenNebula. Expert in CPU, RAM, disk, network, load issues.",
                llm=llm, verbose=False)
            task = Task(
                description=(f"ALERTS:\n{alert_block}\nMETRICS: {metrics_block}\n"
                             "Reply ONLY with a JSON array, no markdown.\n"
                             '[{"step":1,"action":"...","target":"...","metric":"..."}]'),
                expected_output="Valid JSON array of 3 steps.", agent=agent)
            result   = Crew(agents=[agent], tasks=[task], process=Process.sequential).kickoff()
            plan_str = str(result).replace("```json","").replace("```","").strip()
            self.state["plan"] = json.loads(plan_str)
            add_log("SUCCESS", f"AI plan ready ({len(self.state['plan'])} steps).")
        except Exception as exc:
            add_log("ERROR", f"AI planning failed: {exc}")
            self.state["plan"] = [
                {"step":1,"action":"Manual intervention required","target":"SYSTEM_ADMIN","metric":"all"},
                {"step":2,"action":"Check Prometheus/Grafana","target":"GRAFANA","metric":"all"},
            ]
        self._wait_for_approval()

    # ── Execute ───────────────────────────────────────────────────────────────
    def _wait_for_approval(self):
        self.state["current_phase"]  = "WAITING_APPROVAL"
        self.state["execute_status"] = "Awaiting admin decision in Chatbox"
        add_log("AWAIT", "Plan ready. Approve or dismiss via Chatbox.")
        while self.state["current_phase"] == "WAITING_APPROVAL" and self.is_running:
            snap = self._collect()
            
            # Đã thêm rx, tx vào dict để cập nhật state trong lúc chờ
            self.state["metrics"].update({
                "cpu": snap.cpu_pct, "ram_avail_pct": snap.ram_avail_pct,
                "disk_used_pct": snap.disk_used_pct, "net_util_pct": snap.net_util_pct,
                "load1": snap.load1,
                "rx": snap.rx_mbps, "tx": snap.tx_mbps,
            })
            if not self._demo_spike:
                if not [a for a in self._evaluate(snap) if a["level"] == "CRITICAL"]:
                    add_log("SUCCESS", "All metrics safe — auto-resolving.")
                    self.finish_execution()
                    return
            time.sleep(5)

    def finish_execution(self):
        self._demo_spike = self._cpu_warn_since = self._cpu_crit_since = None
        self._demo_spike = False
        self.state.update({"plan":[],"alerts":[],"current_phase":"MONITOR","execute_status":"Resolved"})
        add_log("SUCCESS", "Incident closed. Resuming normal monitoring.")

    def start(self):
        threading.Thread(target=self.mape_k_loop, daemon=True).start()
        add_log("INFO", "AIAgentWorker background thread started.")
