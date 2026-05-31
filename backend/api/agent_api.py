from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

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