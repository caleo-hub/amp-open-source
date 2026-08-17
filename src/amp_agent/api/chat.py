"""Small LangGraph-compatible surface used by the AMP Chat web app."""
from __future__ import annotations
import asyncio, json
from uuid import UUID, uuid4
from typing import Literal
from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from ..persistence.chat import get_thread, list_threads, update_thread, thread_runs, thread_events, resume_approval
from ..persistence.repositories import get_default_workspace, get_execution, get_execution_input
from ..persistence.runtime import request_cancel

router = APIRouter(tags=["chat"])

class ThreadCreate(BaseModel):
    title: str | None = Field(default=None, max_length=120)

class ThreadPatch(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    archived: bool | None = None

class RunRequest(BaseModel):
    assistant_id: str = "amp"
    input: dict = Field(default_factory=dict)
    command: dict | None = None
    metadata: dict = Field(default_factory=dict)
    stream_mode: list[str] = Field(default_factory=lambda: ["messages", "updates", "events"])
    run_id: UUID | None = None

class CancelRequest(BaseModel):
    reason: Literal["user_requested", "operator_requested"] = "user_requested"

def _thread(row: dict) -> dict:
    value = dict(row); value["thread_id"] = value.pop("id"); value["status"] = "archived" if value.get("archived_at") else "active"; return value

def _status(value: str | None) -> str:
    return {"succeeded": "completed", "waiting_approval": "interrupted"}.get(value or "", value or "queued")

def _run(row: dict) -> dict:
    value = dict(row); value["run_id"] = value.get("execution_id", value.get("id")); value["thread_id"] = value.get("conversation_id"); value["status"] = _status(value.get("status")); return value

def _messages(body: RunRequest) -> list[dict]:
    value = body.input.get("messages") if isinstance(body.input, dict) else None
    if value is None and isinstance(body.input, dict) and body.input.get("content"): value = [{"role": "user", "content": body.input["content"]}]
    return value if isinstance(value, list) else []

def _resume_decision(resume: object) -> dict:
    if resume is True: return {"type": "approve"}
    if resume is False: return {"type": "reject"}
    if isinstance(resume, dict): return {"type": "edit", "arguments": resume}
    raise ValueError("Decisão de interrupt inválida.")

async def _stream(execution_id: UUID, cursor: int, request: Request):
    from .app import _execution_event_stream
    async for chunk in _execution_event_stream(execution_id, cursor):
        if await request.is_disconnected(): break
        yield chunk

def _snapshot(snapshot) -> dict:
    values = getattr(snapshot, "values", None) or {}; messages = []
    for message in values.get("messages", []) if isinstance(values, dict) else []:
        messages.append({"role": getattr(message, "type", "message"), "type": getattr(message, "type", "message"), "content": getattr(message, "content", str(message)), "id": getattr(message, "id", None), "tool_calls": getattr(message, "tool_calls", None)})
    state = dict(values) if isinstance(values, dict) else {}
    if messages: state["messages"] = messages
    config = getattr(snapshot, "config", {}) or {}; parent = getattr(snapshot, "parent_config", {}) or {}
    return {"values": state, "next": list(getattr(snapshot, "next", ()) or ()), "metadata": getattr(snapshot, "metadata", None), "config": config, "checkpoint_id": config.get("configurable", {}).get("checkpoint_id"), "parent_checkpoint_id": parent.get("configurable", {}).get("checkpoint_id"), "created_at": getattr(snapshot, "created_at", None)}

@router.get("/threads")
def threads(include_archived: bool = False, limit: int = Query(50, ge=1, le=100)):
    workspace = get_default_workspace()
    if not workspace: raise HTTPException(503, "Workspace bootstrap indisponível.")
    return {"threads": [_thread(item) for item in list_threads(workspace["id"], include_archived=include_archived, limit=limit)]}

@router.post("/threads", status_code=201)
def create_thread(body: ThreadCreate):
    from .app import create_conversation
    item = create_conversation("ui")
    if body.title: item = update_thread(item["id"], title=body.title) or item
    return _thread(item)

@router.get("/threads/{thread_id}")
def thread(thread_id: UUID):
    item = get_thread(thread_id)
    if not item: raise HTTPException(404, "Thread não encontrada.")
    return _thread(item)

@router.patch("/threads/{thread_id}")
def patch_thread(thread_id: UUID, body: ThreadPatch):
    try: item = update_thread(thread_id, title=body.title, archived=body.archived)
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc
    if not item: raise HTTPException(404, "Thread não encontrada.")
    return _thread(item)

@router.get("/threads/{thread_id}/runs")
def runs(thread_id: UUID, limit: int = Query(100, ge=1, le=200)):
    if not get_thread(thread_id): raise HTTPException(404, "Thread não encontrada.")
    return {"runs": [_run(item) for item in thread_runs(thread_id, limit)]}

@router.get("/threads/{thread_id}/runs/{run_id}")
def run(thread_id: UUID, run_id: UUID):
    item = get_execution(run_id)
    if not item or item.get("conversation_id") != thread_id: raise HTTPException(404, "Run não encontrado.")
    return _run(item)

@router.get("/threads/{thread_id}/state")
async def state(request: Request, thread_id: UUID):
    if not get_thread(thread_id): raise HTTPException(404, "Thread não encontrada.")
    snapshot = await request.app.state.langgraph_graph.aget_state({"configurable": {"thread_id": str(thread_id)}})
    return {"thread_id": str(thread_id), "state": _snapshot(snapshot) if snapshot else None}

@router.get("/threads/{thread_id}/history")
async def history(request: Request, thread_id: UUID, limit: int = Query(100, ge=1, le=500)):
    if not get_thread(thread_id): raise HTTPException(404, "Thread não encontrada.")
    config = {"configurable": {"thread_id": str(thread_id)}}; snapshots = []
    async for item in request.app.state.langgraph_graph.aget_state_history(config, limit=limit): snapshots.append(_snapshot(item))
    return {"thread_id": str(thread_id), "checkpoints": snapshots}

@router.post("/threads/{thread_id}/runs/stream")
async def run_stream(thread_id: UUID, body: RunRequest, request: Request, last_event_id: str | None = Header(None, alias="Last-Event-ID"), idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    if not get_thread(thread_id): raise HTTPException(404, "Thread não encontrada.")
    command = body.command or {}; resume = command.get("resume") if isinstance(command, dict) else None
    if resume is not None:
        if not body.run_id: raise HTTPException(422, "run_id é obrigatório para retomar.")
        execution = get_execution(body.run_id)
        if not execution or execution.get("conversation_id") != thread_id: raise HTTPException(404, "Run não encontrado.")
        try: decision = _resume_decision(resume)
        except ValueError as exc: raise HTTPException(422, str(exc)) from exc
        resume_approval(body.run_id, {**decision, "tool_call_id": "approval"}); execution_id = body.run_id
    else:
        messages = [item for item in _messages(body) if item.get("role") in {"user", "human"}]
        if not messages: raise HTTPException(422, "input.messages precisa conter uma mensagem user.")
        from .app import enqueue_message
        result = enqueue_message(conversation_id=thread_id, content=str(messages[-1].get("content", "")).strip(), source="ui", request_id=str(uuid4()), idempotency_key=idempotency_key, deadline_seconds=None, reply_channel=None, priority=0); execution_id = result["execution"]["id"]
    try: cursor = max(0, int(last_event_id or 0))
    except ValueError as exc: raise HTTPException(422, "Last-Event-ID inválido.") from exc
    return StreamingResponse(_stream(execution_id, cursor, request), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@router.get("/threads/{thread_id}/stream")
async def thread_stream(thread_id: UUID, request: Request, last_event_id: str | None = Header(None, alias="Last-Event-ID")):
    if not get_thread(thread_id): raise HTTPException(404, "Thread não encontrada.")
    try: cursor = int(last_event_id or 0)
    except ValueError as exc: raise HTTPException(422, "Last-Event-ID inválido.") from exc
    async def source():
        sent = cursor
        while True:
            rows = thread_events(thread_id)
            for row in rows:
                sequence = int(row["stream_sequence"])
                if sequence <= sent: continue
                sent = sequence; payload = json.dumps(row, ensure_ascii=False, default=str, separators=(",", ":")); yield f"id: {sequence}\nevent: {row.get('event_name', 'execution.event')}\ndata: {payload}\n\n"
            if await request.is_disconnected(): break
            yield ": heartbeat\n\n"; await asyncio.sleep(.5)
    return StreamingResponse(source(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@router.post("/threads/{thread_id}/runs/{run_id}/cancel")
def cancel(thread_id: UUID, run_id: UUID, body: CancelRequest | None = None):
    if not get_thread(thread_id): raise HTTPException(404, "Thread não encontrada.")
    result = request_cancel(run_id, (body or CancelRequest()).reason, {"type": "ui"})
    if not result.get("found"): raise HTTPException(404, "Run não encontrado.")
    return {"run_id": str(run_id), **result}

@router.post("/threads/{thread_id}/runs/{run_id}/retry", status_code=202)
def retry(thread_id: UUID, run_id: UUID):
    original = get_execution_input(run_id)
    if not original or original.get("conversation_id") != thread_id: raise HTTPException(404, "Run não encontrado.")
    from .app import enqueue_message
    result = enqueue_message(conversation_id=thread_id, content=original["content"], source="ui", request_id=str(uuid4()), idempotency_key=str(uuid4()), deadline_seconds=None, reply_channel=None, priority=0)
    return _run(result["execution"])
