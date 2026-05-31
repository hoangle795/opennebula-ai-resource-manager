import os
import uuid
import asyncio
import time
from dotenv import load_dotenv

load_dotenv()
from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, create_model
from typing import Any

from crewai import Agent, Task, Crew, Process, LLM
from crewai.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from api import dashboard_api, agent_api
from ai_worker import AIAgentWorker
from database import init_db, get_recent_logs
from config import GROQ_API_KEY

os.environ.setdefault("GROQ_API_KEY", GROQ_API_KEY)

app = FastAPI(title="NebulaStack AIOps", version="2.0.0")

init_db()
agent = AIAgentWorker()
agent.start()
agent_api.set_agent(agent)

app.include_router(dashboard_api.router, prefix="/api/dashboard")
app.include_router(agent_api.router,    prefix="/api/agent")


@app.get("/api/logs")
async def get_logs():
    return get_recent_logs(20)


task_store: dict = {}

_MCP_SERVER = os.path.join(os.path.dirname(__file__), "mcp_server.py")
_MCP_CONFIG = {
    "nebula_tools": {
        "command":   "python",
        "args":      [_MCP_SERVER],
        "transport": "stdio",
    }
}


class ChatMessage(BaseModel):
    message: str


# ── Tool adapter (không đổi logic, chỉ thêm guard vào description) ──────────
def adapt_mcp_tool(langchain_tool):
    schema_dict = getattr(langchain_tool, "args_schema", {})
    if hasattr(schema_dict, "schema") and callable(schema_dict.schema):
        schema_dict = schema_dict.schema()
    elif not isinstance(schema_dict, dict):
        schema_dict = {}

    properties      = schema_dict.get("properties", {})
    required_fields = schema_dict.get("required", [])

    if not properties:
        class SafeSchema(BaseModel):
            execute_flag: bool = Field(
                ...,
                description="MANDATORY: You must set this to true to execute the tool."
            )
        FinalSchema = SafeSchema
        tool_desc = (
            langchain_tool.description
            + "\n!!! IMPORTANT: pass {'execute_flag': true} to call this tool. "
            "Do NOT call any tool not listed here (e.g. brave_search is FORBIDDEN). !!!"
        )
    else:
        fields = {}
        for key, val in properties.items():
            desc = val.get("description", "No description")
            if key in required_fields:
                fields[key] = (Any, Field(..., description=desc))
            else:
                fields[key] = (Any, Field(default=None, description=desc))
        safe_name   = "".join(c for c in langchain_tool.name if c.isalnum())
        FinalSchema = create_model(f"{safe_name}Schema", **fields)
        tool_desc   = langchain_tool.description

    class AdaptedTool(BaseTool):
        name:        str            = langchain_tool.name
        description: str            = tool_desc
        args_schema: type[BaseModel] = FinalSchema

        def _run(self, **kwargs):
            valid_args = {k: v for k, v in kwargs.items() if k in properties}
            return langchain_tool.invoke(valid_args)

    return AdaptedTool()


async def _run_chat_async(task_id: str, user_msg: str):
    try:
        mcp_client    = MultiServerMCPClient(_MCP_CONFIG)
        raw_mcp_tools = await mcp_client.get_tools()
        mcp_tools     = [adapt_mcp_tool(t) for t in raw_mcp_tools]

        # ── FIX 1: model 70b + giới hạn output tokens chặt ─────────────────
        agent_llm = LLM(
            model="groq/llama-3.3-70b-versatile",
            api_key=os.getenv("GROQ_API_KEY"),
            temperature=0.0,
            max_tokens=800,   # ← cap output, tránh vượt TPM
        )

        tool_names = ", ".join(t.name for t in mcp_tools)

        # ── FIX 2: gộp 2 agent → 1 agent, tiết kiệm ~50% token ─────────────
        single_agent = Agent(
            role="AIOps Engineer",
            goal="Query system metrics via tools then reply with a concise Markdown report.",
            backstory=(
                f"Senior SRE. Allowed tools: [{tool_names}]. "
                "NEVER call brave_search or any unlisted tool."
            ),
            tools=mcp_tools,
            llm=agent_llm,
            verbose=False,
        )

        # ── FIX 3: prompt ngắn gọn, chỉ 1 task duy nhất ───────────────────
        single_task = Task(
            description=(
                f"Request: '{user_msg}'\n"
                "1. Call get_system_summary() — one call covers all metrics.\n"
                "2. Reply with: metric table (value + status) | root cause | actions.\n"
                "Keep total response under 400 words."
            ),
            expected_output="Markdown report: table + root cause + actions.",
            agent=single_agent,
        )

        crew = Crew(
            agents=[single_agent],
            tasks=[single_task],
            process=Process.sequential,
        )
        # ── FIX 4: retry tự động khi bị rate-limit ──────────────────────────
        loop = asyncio.get_event_loop()

        def kickoff_with_retry(max_retries: int = 4):
            for attempt in range(max_retries):
                try:
                    return crew.kickoff()
                except Exception as e:
                    err = str(e)
                    if "rate_limit_exceeded" in err or "RateLimitError" in err:
                        # Groq trả về thời gian chờ trong message, parse ra nếu có
                        wait = 15.0
                        import re
                        m = re.search(r"try again in ([0-9.]+)s", err)
                        if m:
                            wait = float(m.group(1)) + 1.0
                        if attempt < max_retries - 1:
                            time.sleep(wait)
                            continue
                    raise  # lỗi khác hoặc hết retry → raise lên trên

        result = await loop.run_in_executor(None, kickoff_with_retry)
        task_store[task_id] = {"status": "completed", "response": str(result)}

    except Exception as exc:
        task_store[task_id] = {"status": "error", "response": f"AI Error: {exc}"}


def _chat_thread_entry(task_id: str, user_msg: str):
    asyncio.run(_run_chat_async(task_id, user_msg))


@app.post("/api/chat/submit")
async def submit_chat(req: ChatMessage, background_tasks: BackgroundTasks):
    task_id = str(uuid.uuid4())
    task_store[task_id] = {"status": "processing"}
    background_tasks.add_task(_chat_thread_entry, task_id, req.message)
    return {"status": "success", "task_id": task_id}


@app.get("/api/chat/status/{task_id}")
async def get_chat_status(task_id: str):
    result = task_store.get(task_id)
    if not result:
        return {"status": "error", "response": "Task not found."}
    return result


# ── Frontend ──────────────────────────────────────────────────────────────────
_TEMPLATES = os.path.join(os.path.dirname(__file__), "..", "frontend", "templates")


def _serve(filename: str) -> str:
    with open(os.path.join(_TEMPLATES, filename), encoding="utf-8") as f:
        return f.read()


@app.get("/",            response_class=HTMLResponse)
async def serve_dashboard():   return _serve("dashboard.html")

@app.get("/agent",       response_class=HTMLResponse)
async def serve_agent():       return _serve("ai_agent.html")

@app.get("/system-logs", response_class=HTMLResponse)
async def serve_system_logs(): return _serve("system_logs.html")