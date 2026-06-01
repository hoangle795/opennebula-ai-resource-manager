import os
import uuid
import asyncio
import time
import json
import re
from dotenv import load_dotenv

load_dotenv()
from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

from crewai import Agent, Task, Crew, Process, LLM
from crewai.tools import BaseTool

from api import dashboard_api, agent_api
from ai_worker import AIAgentWorker
from database import init_db, get_recent_logs
from config import GROQ_API_KEY

os.environ.setdefault("GROQ_API_KEY", GROQ_API_KEY)

app = FastAPI(title="NebulaStack AIOps", version="2.0.0")

init_db()
_worker = AIAgentWorker()
_worker.start()
agent_api.set_agent(_worker)

app.include_router(dashboard_api.router, prefix="/api/dashboard")
app.include_router(agent_api.router,    prefix="/api/agent")


@app.get("/api/logs")
async def get_logs():
    return get_recent_logs(20)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "nebulastack-aiops",
        "agent_running": _worker.is_running,
        "agent_phase": _worker.state.get("current_phase"),
    }


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    state = _worker.state
    metric_state = state.get("metrics", {})
    phase = state.get("current_phase", "UNKNOWN")
    status = state.get("analysis", {}).get("status", "UNKNOWN")
    alerts = state.get("alerts", [])
    lines = [
        "# HELP ai_agent_up AIAgentWorker running state.",
        "# TYPE ai_agent_up gauge",
        f"ai_agent_up {1 if _worker.is_running else 0}",
        "# HELP ai_agent_autonomous_mode Autonomous execution mode.",
        "# TYPE ai_agent_autonomous_mode gauge",
        f"ai_agent_autonomous_mode {1 if _worker.autonomous_mode else 0}",
        "# HELP ai_agent_metric Current metric values collected by the AI worker.",
        "# TYPE ai_agent_metric gauge",
        f'ai_agent_metric{{metric="cpu_pct"}} {float(metric_state.get("cpu", 0.0))}',
        f'ai_agent_metric{{metric="ram_avail_pct"}} {float(metric_state.get("ram_avail_pct", 100.0))}',
        f'ai_agent_metric{{metric="disk_used_pct"}} {float(metric_state.get("disk_used_pct", 0.0))}',
        f'ai_agent_metric{{metric="net_util_pct"}} {float(metric_state.get("net_util_pct", 0.0))}',
        f'ai_agent_metric{{metric="load1"}} {float(metric_state.get("load1", 0.0))}',
        f'ai_agent_metric{{metric="cpu_cores"}} {float(metric_state.get("cpu_cores", 1.0))}',
        "# HELP ai_agent_alerts Active AI agent alerts by level.",
        "# TYPE ai_agent_alerts gauge",
        f'ai_agent_alerts{{level="warning"}} {sum(1 for a in alerts if a.get("level") == "WARNING")}',
        f'ai_agent_alerts{{level="critical"}} {sum(1 for a in alerts if a.get("level") == "CRITICAL")}',
        "# HELP ai_agent_plan_steps Current remediation plan size.",
        "# TYPE ai_agent_plan_steps gauge",
        f"ai_agent_plan_steps {len(state.get('plan', []))}",
        "# HELP ai_agent_phase Current AI agent phase as an info metric.",
        "# TYPE ai_agent_phase gauge",
        f'ai_agent_phase{{phase="{phase}",status="{status}"}} 1',
    ]
    return "\n".join(lines) + "\n"


task_store: dict = {}


class ChatMessage(BaseModel):
    message: str


# ══════════════════════════════════════════════════════════════════════════════
# DIRECT TOOLS — đọc thẳng từ agent.state (data thật, không qua MCP)
# ══════════════════════════════════════════════════════════════════════════════

class _NoArgs(BaseModel):
    """Schema dùng chung cho các tool không có tham số — bắt buộc để Groq không báo lỗi."""
    execute: bool = Field(default=True, description="Set to true to run this tool.")


class LiveMetricsTool(BaseTool):
    """Đọc metrics thật từ AIAgentWorker đang chạy (đã poll Prometheus liên tục)."""
    name: str        = "get_live_metrics"
    description: str = (
        "Returns REAL live system metrics collected from Prometheus. "
        "ALWAYS call this tool first. NEVER guess or estimate any metric value."
    )
    args_schema: type[BaseModel] = _NoArgs

    def _run(self, execute: bool = True, **kwargs) -> str:
        w = agent_api._agent
        if not w:
            return "ERROR: Worker agent not running."
        m       = w.state["metrics"]
        alerts  = w.state["alerts"]
        analysis= w.state["analysis"]
        phase   = w.state["current_phase"]

        lines = [
            "=== LIVE SYSTEM METRICS (real data from Prometheus) ===",
            f"CPU Usage      : {m.get('cpu', 0):.1f}%",
            f"RAM Available  : {m.get('ram_avail_pct', 100):.1f}%  "
            f"(RAM Used: {100 - m.get('ram_avail_pct', 100):.1f}%)",
            f"Disk Used      : {m.get('disk_used_pct', 0):.1f}%",
            f"Network RX     : {m.get('rx', 0):.2f} Mbps",
            f"Network TX     : {m.get('tx', 0):.2f} Mbps",
            f"Net Utilisation: {m.get('net_util_pct', 0):.1f}%",
            f"Load Avg (1m)  : {m.get('load1', 0):.2f}  /  {m.get('cpu_cores', 1)} cores",
            f"System Phase   : {phase}",
            f"System Status  : {analysis.get('status', 'Unknown')}",
            f"Active Alerts  : {len(alerts)}",
        ]
        if alerts:
            lines.append("\nActive Alerts:")
            for a in alerts:
                lines.append(f"  [{a['level']}] {a['metric'].upper()}: {a['message']}")
        return "\n".join(lines)


class ScaleClusterTool(BaseTool):
    name: str        = "recommend_scale_cluster"
    description: str = "Provide recommendation to scale up the OpenNebula cluster."
    args_schema: type[BaseModel] = _NoArgs

    def _run(self, execute: bool = True, **kwargs) -> str:
        return (
            "RECOMMENDATION — Scale Up Cluster:\n"
            "  1. SSH to OpenNebula controller.\n"
            "  2. Add host: onehost create <hostname> -i kvm -v kvm\n"
            "  3. Verify: onehost list\n"
            "  Note: Admin must execute — this is advisory only."
        )


class RestartNodesTool(BaseTool):
    name: str        = "recommend_restart_nodes"
    description: str = "Provide recommendation to restart API/worker nodes."
    args_schema: type[BaseModel] = _NoArgs

    def _run(self, execute: bool = True, **kwargs) -> str:
        return (
            "RECOMMENDATION — Restart API Nodes:\n"
            "  1. List VMs: onevm list\n"
            "  2. Reboot: onevm reboot <vm_id>\n"
            "  3. Monitor: onevm show <vm_id>\n"
            "  Note: Admin must execute — this is advisory only."
        )


class MigrateVMTool(BaseTool):
    name: str        = "recommend_migrate_vm"
    description: str = (
        "Provide recommendation to live-migrate a VM. "
        "Requires vm_id (int) and target_host_id (int)."
    )

    class ArgsSchema(BaseModel):
        vm_id:          int = Field(..., description="ID of the VM to migrate.")
        target_host_id: int = Field(..., description="ID of the target host.")

    args_schema: type[BaseModel] = ArgsSchema

    def _run(self, vm_id: int, target_host_id: int, **kwargs) -> str:
        return (
            f"RECOMMENDATION — Migrate VM {vm_id} → Host {target_host_id}:\n"
            f"  Command: onevm migrate {vm_id} {target_host_id} --live\n"
            f"  Monitor: onevm show {vm_id}\n"
            "  Note: Admin must execute — this is advisory only."
        )


_CHAT_TOOLS  = [LiveMetricsTool(), ScaleClusterTool(), RestartNodesTool(), MigrateVMTool()]
_TOOL_NAMES  = ", ".join(t.name for t in _CHAT_TOOLS)


# ══════════════════════════════════════════════════════════════════════════════
# CHAT PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

async def _run_chat_async(task_id: str, user_msg: str):
    try:
        llm = LLM(
            model="groq/llama-3.3-70b-versatile",
            api_key=os.getenv("GROQ_API_KEY"),
            temperature=0.0,
            max_tokens=800,
        )

        agent = Agent(
            role="AIOps Advisor",
            goal=(
                "Answer admin questions about system health using ONLY real data "
                "from get_live_metrics(). Provide recommendations — never execute actions."
            ),
            backstory=(
                f"Senior SRE for NebulaStack OpenNebula cluster. "
                f"Allowed tools: [{_TOOL_NAMES}]. "
                "Rule 1: ALWAYS call get_live_metrics() first to get real numbers. "
                "Rule 2: NEVER invent or estimate any metric. "
                "Rule 3: You advise — the admin decides and executes."
            ),
            tools=_CHAT_TOOLS,
            llm=llm,
            verbose=False,
        )

        task = Task(
            description=(
                f"Admin question: '{user_msg}'\n\n"
                "Instructions:\n"
                "1. Call get_live_metrics() to get real current data.\n"
                "2. Use ONLY the numbers returned by that tool.\n"
                "3. Format your answer as:\n"
                "   - A Markdown table of relevant metrics (value + level)\n"
                "   - 2-3 sentence analysis\n"
                "   - Bullet list of recommended actions (advisory only)\n"
                "4. Keep response under 350 words."
            ),
            expected_output="Markdown: metrics table + analysis + advisory recommendations.",
            agent=agent,
        )

        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential)
        loop = asyncio.get_event_loop()

        def _kickoff_retry(max_retries: int = 4):
            for attempt in range(max_retries):
                try:
                    return crew.kickoff()
                except Exception as exc:
                    err = str(exc)
                    if "rate_limit_exceeded" in err or "RateLimitError" in err:
                        wait = 15.0
                        m = re.search(r"try again in ([0-9.]+)s", err)
                        if m:
                            wait = float(m.group(1)) + 1.5
                        if attempt < max_retries - 1:
                            time.sleep(wait)
                            continue
                    raise

        result = await loop.run_in_executor(None, _kickoff_retry)
        task_store[task_id] = {"status": "completed", "response": str(result)}

    except Exception as exc:
        task_store[task_id] = {"status": "error", "response": f"AI Error: {exc}"}


def _chat_thread(task_id: str, user_msg: str):
    asyncio.run(_run_chat_async(task_id, user_msg))


@app.post("/api/chat/submit")
async def submit_chat(req: ChatMessage, background_tasks: BackgroundTasks):
    task_id = str(uuid.uuid4())
    task_store[task_id] = {"status": "processing"}
    background_tasks.add_task(_chat_thread, task_id, req.message)
    return {"status": "success", "task_id": task_id}


@app.get("/api/chat/status/{task_id}")
async def get_chat_status(task_id: str):
    return task_store.get(task_id) or {"status": "error", "response": "Task not found."}


# ── Frontend ──────────────────────────────────────────────────────────────────
_TEMPLATES = os.path.join(os.path.dirname(__file__), "..", "frontend", "templates")


def _serve(name: str) -> str:
    with open(os.path.join(_TEMPLATES, name), encoding="utf-8") as f:
        return f.read()


@app.get("/",            response_class=HTMLResponse)
async def serve_dashboard():   return _serve("dashboard.html")

@app.get("/agent",       response_class=HTMLResponse)
async def serve_agent():       return _serve("ai_agent.html")

@app.get("/system-logs", response_class=HTMLResponse)
async def serve_system_logs(): return _serve("system_logs.html")
