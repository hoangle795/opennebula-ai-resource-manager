from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from database import add_log

router   = APIRouter()
_agent   = None


def set_agent(agent):
    global _agent
    _agent = agent


def _require_agent():
    if not _agent:
        raise HTTPException(status_code=503, detail="Agent not initialized.")


@router.get("/state")
async def get_agent_state():
    _require_agent()
    return {
        "status":          "success",
        "agent_state":     _agent.state,
        "autonomous_mode": _agent.autonomous_mode,
    }


class ActionReq(BaseModel):
    action: str  # "approve" | "dismiss"


def _normalize_alertmanager_alert(alert: dict) -> dict:
    labels = alert.get("labels", {}) or {}
    annotations = alert.get("annotations", {}) or {}
    level = (labels.get("severity") or "warning").upper()
    metric = (labels.get("metric") or labels.get("alertname") or "unknown").lower()
    summary = annotations.get("summary") or labels.get("alertname") or "Prometheus alert"
    description = annotations.get("description") or ""
    message = f"{summary}. {description}".strip()
    return {
        "metric": metric,
        "level": level,
        "value": labels.get("instance", "n/a"),
        "message": message,
    }


def _build_prometheus_plan(alerts: list[dict]) -> list[dict]:
    metrics = {a["metric"] for a in alerts}
    plan = []

    if "cpu" in metrics:
        plan.extend([
            {"step": 1, "action": "Identify top CPU consumers on the affected host", "target": "HOST_NODE", "metric": "cpu"},
            {"step": 2, "action": "Migrate or throttle non-critical VMs from the overloaded host", "target": "OPENNEBULA", "metric": "cpu"},
            {"step": 3, "action": "Add capacity or rebalance workload if CPU remains above threshold", "target": "CLUSTER", "metric": "cpu"},
        ])

    if "ram" in metrics:
        plan.extend([
            {"step": len(plan) + 1, "action": "Check VMs with high memory allocation and active memory pressure", "target": "OPENNEBULA", "metric": "ram"},
            {"step": len(plan) + 2, "action": "Migrate memory-heavy VMs to a host with more available RAM", "target": "OPENNEBULA", "metric": "ram"},
            {"step": len(plan) + 3, "action": "Stop or resize unnecessary demo VMs after admin confirmation", "target": "VM_POOL", "metric": "ram"},
        ])

    if "disk" in metrics:
        plan.extend([
            {"step": len(plan) + 1, "action": "Identify large files, logs, images, and VM disks on the affected mountpoint", "target": "HOST_NODE", "metric": "disk"},
            {"step": len(plan) + 2, "action": "Clean safe temporary data and rotate oversized logs", "target": "HOST_NODE", "metric": "disk"},
            {"step": len(plan) + 3, "action": "Move or resize VM storage after administrator confirmation", "target": "OPENNEBULA_DATASTORE", "metric": "disk"},
        ])

    if "network" in metrics:
        plan.extend([
            {"step": len(plan) + 1, "action": "Identify top network consumers and affected interfaces", "target": "HOST_NODE", "metric": "network"},
            {"step": len(plan) + 2, "action": "Throttle or migrate non-critical high-traffic VMs", "target": "OPENNEBULA", "metric": "network"},
            {"step": len(plan) + 3, "action": "Validate bandwidth cap and rebalance traffic across hosts", "target": "NETWORK", "metric": "network"},
        ])

    if "load_avg" in metrics:
        plan.extend([
            {"step": len(plan) + 1, "action": "Correlate load average with CPU, disk I/O, and blocked processes", "target": "HOST_NODE", "metric": "load_avg"},
            {"step": len(plan) + 2, "action": "Reduce queue pressure by migrating or pausing low-priority workloads", "target": "OPENNEBULA", "metric": "load_avg"},
            {"step": len(plan) + 3, "action": "Scale capacity if sustained load remains above core count threshold", "target": "CLUSTER", "metric": "load_avg"},
        ])

    if not plan:
        plan = [
            {"step": 1, "action": "Inspect Prometheus alert context and affected instance", "target": "PROMETHEUS", "metric": "all"},
            {"step": 2, "action": "Validate current host metrics in Grafana and dashboard", "target": "GRAFANA", "metric": "all"},
            {"step": 3, "action": "Escalate to administrator if the alert persists", "target": "SRE", "metric": "all"},
        ]

    return [{**item, "step": idx} for idx, item in enumerate(plan[:3], start=1)]


@router.post("/prometheus-webhook")
async def prometheus_webhook(request: Request):
    _require_agent()
    payload = await request.json()
    firing = [
        _normalize_alertmanager_alert(alert)
        for alert in payload.get("alerts", [])
        if alert.get("status") == "firing"
    ]

    if not firing:
        if payload.get("status") == "resolved":
            add_log("SUCCESS", "Prometheus alerts resolved via Alertmanager webhook.")
            _agent.finish_execution()
        return {"status": "success", "message": "No firing alerts.", "alerts": 0}

    has_critical = any(alert["level"] == "CRITICAL" for alert in firing)
    summary = "; ".join(alert["message"] for alert in firing)
    _agent.state["alerts"] = firing
    _agent.state["analysis"] = {
        "confidence": 97.0,
        "status": "CRITICAL" if has_critical else "WARNING",
        "details": summary,
    }
    _agent.state["plan"] = _build_prometheus_plan(firing)
    _agent.state["current_phase"] = "WAITING_APPROVAL"
    _agent.state["execute_status"] = "Prometheus alert received. Awaiting admin approval."
    add_log("ERROR" if has_critical else "WARN", f"Alertmanager webhook received: {summary}")
    add_log("SUCCESS", f"Prometheus-driven AI plan ready ({len(_agent.state['plan'])} steps).")
    return {"status": "success", "message": "Alert accepted and plan generated.", "alerts": len(firing)}


@router.post("/approve")
async def handle_action(req: ActionReq):
    _require_agent()
    if req.action == "approve":
        if _agent.state["current_phase"] != "WAITING_APPROVAL":
            return {"status": "failed", "message": "No plan is currently awaiting approval."}
        _agent.state["current_phase"]  = "EXECUTE"
        _agent.state["execute_status"] = "Executing…"
        _agent.finish_execution()
        return {"status": "success", "message": "Plan approved and executed."}

    if req.action == "dismiss":
        _agent.finish_execution()
        return {"status": "success", "message": "Alert dismissed."}

    return {"status": "failed", "message": f"Unknown action: {req.action}"}


@router.post("/toggle-autonomous")
async def toggle_autonomous():
    _require_agent()
    _agent.autonomous_mode = not _agent.autonomous_mode
    mode = "enabled" if _agent.autonomous_mode else "disabled"
    return {"status": "success", "autonomous_mode": _agent.autonomous_mode, "message": f"Autonomous mode {mode}."}


@router.post("/trigger-test")
async def trigger_test():
    _require_agent()
    _agent.trigger_anomaly()
    return {"status": "success", "message": "Demo CPU spike triggered (95.8%)."}


@router.post("/reset-test")
async def reset_test():
    _require_agent()
    _agent.reset_anomaly()
    return {"status": "success", "message": "Demo anomaly cleared."}
