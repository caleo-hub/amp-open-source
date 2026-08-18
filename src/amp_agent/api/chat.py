"""Small LangGraph-compatible surface used by the AMP Chat web app."""
from __future__ import annotations
import asyncio, json, ast, re
from uuid import UUID, uuid4
from typing import Any, Literal
from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from ..persistence.chat import (
    append_lifecycle_event,
    get_thread,
    list_threads,
    resume_approval,
    thread_runs,
    thread_stream_events,
    update_thread,
    protocol_json,
)
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


class ProtocolCommand(BaseModel):
    id: int | str | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class SubscribeParams(BaseModel):
    channels: list[str] = Field(default_factory=lambda: ["messages", "values", "updates", "tools", "lifecycle", "input", "custom"])
    namespaces: list[list[str]] | None = None
    depth: int | None = Field(default=None, ge=0)
    since: int | None = Field(default=None, ge=0)


class AGUIRunRequest(BaseModel):
    """Permissive AG-UI run payload; clients differ slightly by version."""
    model_config = ConfigDict(populate_by_name=True)
    messages: list[dict[str, Any]] = Field(default_factory=list)
    input: dict[str, Any] = Field(default_factory=dict)
    # AG-UI uses camelCase while the temporary AMP endpoint used snake_case.
    # Accept both so the durable worker remains the only execution authority.
    thread_id: UUID | None = Field(default=None, validation_alias=AliasChoices("threadId", "thread_id"))
    run_id: str | None = Field(default=None, validation_alias=AliasChoices("runId", "run_id"))
    # CopilotKit sends this when resolving an AG-UI interrupt.  Older clients
    # used an object while newer clients use a one-item list, so accept both.
    resume: list[dict[str, Any]] | dict[str, Any] | None = None

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


def _protocol_response(command: ProtocolCommand, result: dict | None = None) -> dict:
    """Agent Streaming Protocol command response accepted by the TS SDK."""
    return {"id": command.id, "type": "response", "result": result or {}, "meta": {}}


def _protocol_event(row: dict) -> dict:
    return {
        "type": "event",
        "seq": int(row["seq"]),
        "event_id": str(row["seq"]),
        "method": row["method"],
        "params": {**(row.get("params") or {}), "namespace": row.get("namespace") or []},
    }


def _cursor(since: int | None, last_event_id: str | None) -> int:
    try:
        header = int(last_event_id or 0)
    except ValueError as exc:
        raise HTTPException(422, "Last-Event-ID inválido.") from exc
    return max(0, since or 0, header)


def _pending_run(thread_id: UUID) -> dict | None:
    return next((item for item in thread_runs(thread_id) if item.get("status") in {"waiting_approval", "running"}), None)


def _agui_event(
    row: dict,
    *,
    thread_id: UUID,
    client_run_id: str,
    active_message_id: str | None = None,
    pending_interrupt: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Translate the durable AMP v2 stream to portable AG-UI events."""
    method, params = row["method"], row.get("params") or {}
    data = params.get("data") or {}
    run_id = client_run_id
    if method == "lifecycle":
        event = data.get("event") if isinstance(data, dict) else None
        # AG-UI requires RUN_STARTED to be the first event.  The endpoint
        # emits it before the durable snapshot, so the queued audit record is
        # intentionally not projected a second time here.
        if event == "queued":
            return []
        if event in {"completed", "failed", "interrupted"}:
            if event == "completed":
                return [{"type": "RUN_FINISHED", "threadId": str(thread_id), "runId": run_id}]
            # An interrupt is a paused, resumable run, not a failed run.  The
            # AG-UI contract represents it as RUN_FINISHED with an interrupt
            # outcome; emitting RUN_ERROR makes CopilotKit surface a false
            # agent_run_error_event and leaves its heartbeat active.
            if event == "interrupted":
                interrupt = pending_interrupt or {}
                payload = interrupt.get("payload") if isinstance(interrupt, dict) else {}
                payload = payload if isinstance(payload, dict) else {"value": payload}
                interrupt_id = str(
                    interrupt.get("interrupt_id")
                    or interrupt.get("id")
                    or f"amp-interrupt-{row['seq']}"
                )
                summary = _agui_text(payload.get("summary") or payload.get("message") or "Aprovação necessária.")
                item: dict[str, Any] = {
                    "id": interrupt_id,
                    "reason": "tool_call" if interrupt.get("tool_call_id") else "confirmation",
                    "message": summary,
                    "metadata": payload,
                }
                if interrupt.get("tool_call_id"):
                    item["toolCallId"] = str(interrupt["tool_call_id"])
                return [{
                    "type": "RUN_FINISHED",
                    "threadId": str(thread_id),
                    "runId": run_id,
                    "outcome": {"type": "interrupt", "interrupts": [item]},
                }]
            error_message = data.get("error") if isinstance(data, dict) else None
            return [{"type": "RUN_ERROR", "threadId": str(thread_id), "runId": run_id, "message": str(error_message or "A execução falhou.")}]
    if method == "messages" and isinstance(data, dict):
        event, message_id = data.get("event"), data.get("id") or active_message_id or f"amp-{row['seq']}"
        if event == "message-start": return [{"type": "TEXT_MESSAGE_START", "messageId": message_id, "role": "assistant"}]
        if event == "content-block-delta":
            delta = data.get("delta") or {}; text = delta.get("text") if isinstance(delta, dict) else None
            return [{"type": "TEXT_MESSAGE_CONTENT", "messageId": message_id, "delta": text}] if text else []
        if event == "message-finish": return [{"type": "TEXT_MESSAGE_END", "messageId": message_id}]
    if method == "input.requested":
        # The request is carried in the terminal RUN_FINISHED outcome below.
        # Do not emit a parallel CUSTOM event: CopilotKit would treat it as a
        # second, unrelated stream and can keep the run heartbeat alive.
        return []
    return []


def _agui_text(content: Any) -> str:
    """Extract renderable text from LangChain's string-or-block content."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(_agui_text(part) for part in content)
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str):
            return text
        return _agui_text(content.get("content", ""))
    return ""


def _agui_messages(values: dict[str, Any], current_user: dict[str, Any]) -> list[dict[str, Any]]:
    """Project checkpoint messages into the conservative AG-UI v0.0.57 shape."""
    role_map = {"human": "user", "ai": "assistant", "tool": "tool", "system": "system"}
    messages: list[dict[str, Any]] = []
    for message in values.get("messages", []):
        role = role_map.get(getattr(message, "type", ""), getattr(message, "type", "assistant"))
        # This pinned AG-UI client represents normal messages as text. Tool
        # messages require a toolCallId, so they are streamed as lifecycle
        # events rather than copied into a transcript snapshot.
        if role not in {"user", "assistant", "system"}:
            continue
        messages.append({
            "id": str(getattr(message, "id", None) or uuid4()),
            "role": role,
            "content": _agui_text(getattr(message, "content", "")),
        })
    user_id = current_user.get("id") or f"amp-user-{uuid4()}"
    content = _agui_text(current_user.get("content", ""))
    if content and not any(item["id"] == user_id for item in messages):
        messages.append({"id": user_id, "role": "user", "content": content})
    return messages


def _agui_resume_decision(value: object) -> dict[str, Any]:
    """Map AG-UI/CopilotKit interrupt resolution shapes to AMP decisions."""
    item: dict[str, Any]
    if isinstance(value, list):
        item = value[-1] if value and isinstance(value[-1], dict) else {}
    elif isinstance(value, dict):
        item = value
    else:
        item = {"payload": value}
    payload = item.get("payload", item.get("data", item))
    if not isinstance(payload, dict):
        payload = {"value": payload}
    status = str(item.get("status") or item.get("decision") or payload.get("status") or "").lower()
    if status in {"rejected", "reject", "cancelled", "canceled"} or payload.get("approved") is False:
        decision: dict[str, Any] = {"type": "reject"}
    elif status in {"approved", "approve", "resolved", "accepted"} or payload.get("approved") is True:
        decision = {"type": "approve"}
    elif payload.get("type") in {"approve", "reject", "edit"}:
        decision = {"type": payload["type"]}
        if payload["type"] == "edit":
            decision["arguments"] = payload.get("arguments") or payload.get("editedArgs") or {}
    elif "editedArgs" in payload or "arguments" in payload:
        decision = {"type": "edit", "arguments": payload.get("editedArgs") or payload.get("arguments") or {}}
    else:
        decision = {"type": "approve"}
    decision["tool_call_id"] = str(item.get("interruptId") or item.get("interrupt_id") or payload.get("tool_call_id") or "approval")
    return decision

def _snapshot(snapshot) -> dict:
    values = getattr(snapshot, "values", None) or {}; messages = []
    for message in values.get("messages", []) if isinstance(values, dict) else []:
        messages.append({"role": getattr(message, "type", "message"), "type": getattr(message, "type", "message"), "content": getattr(message, "content", str(message)), "id": getattr(message, "id", None), "tool_calls": getattr(message, "tool_calls", None)})
    state = dict(values) if isinstance(values, dict) else {}
    if messages: state["messages"] = messages
    config = getattr(snapshot, "config", {}) or {}; parent = getattr(snapshot, "parent_config", {}) or {}
    return {"values": protocol_json(state), "next": list(getattr(snapshot, "next", ()) or ()), "metadata": protocol_json(getattr(snapshot, "metadata", None)), "config": protocol_json(config), "checkpoint_id": config.get("configurable", {}).get("checkpoint_id"), "parent_checkpoint_id": parent.get("configurable", {}).get("checkpoint_id"), "created_at": getattr(snapshot, "created_at", None)}

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
    return _snapshot(snapshot) if snapshot else {"values": {}, "next": [], "config": {}}

@router.api_route("/threads/{thread_id}/history", methods=["GET", "POST"])
async def history(request: Request, thread_id: UUID, limit: int = Query(100, ge=1, le=500)):
    if not get_thread(thread_id): raise HTTPException(404, "Thread não encontrada.")
    config = {"configurable": {"thread_id": str(thread_id)}}; snapshots = []
    async for item in request.app.state.langgraph_graph.aget_state_history(config, limit=limit): snapshots.append(_snapshot(item))
    return {"thread_id": str(thread_id), "checkpoints": snapshots}


@router.post("/threads/{thread_id}/commands")
def commands(thread_id: UUID, command: ProtocolCommand, idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    """Small Agent Streaming Protocol command surface used by @langchain/react."""
    if not get_thread(thread_id):
        raise HTTPException(404, "Thread não encontrada.")
    if command.method == "run.start":
        input_value = command.params.get("input") or {}
        request_body = RunRequest(input=input_value, metadata=command.params.get("metadata") or {})
        messages = [item for item in _messages(request_body) if item.get("role") in {"user", "human"} or item.get("type") in {"human", "user"}]
        if not messages:
            raise HTTPException(422, "input.messages precisa conter uma mensagem user.")
        content = messages[-1].get("content", "")
        if isinstance(content, list):
            content = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
        from .app import enqueue_message
        result = enqueue_message(
            conversation_id=thread_id,
            content=str(content).strip(),
            source="ui",
            request_id=str(uuid4()),
            idempotency_key=idempotency_key or str(uuid4()),
            deadline_seconds=None,
            reply_channel=None,
            priority=0,
        )
        execution = result["execution"]
        append_lifecycle_event(execution["id"], "queued")
        return _protocol_response(command, {"run_id": str(execution["id"])})
    if command.method == "input.respond":
        run = _pending_run(thread_id)
        if not run:
            raise HTTPException(409, "Não há interrupt pendente nesta thread.")
        response = command.params.get("response")
        try:
            decision = _resume_decision(response)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        resume_approval(run["id"], {**decision, "tool_call_id": str(command.params.get("interrupt_id") or "approval")})
        append_lifecycle_event(run["id"], "queued")
        return _protocol_response(command, {"run_id": str(run["id"])})
    raise HTTPException(422, f"Comando não suportado: {command.method}")


@router.post("/threads/{thread_id}/stream")
async def protocol_stream(thread_id: UUID, body: SubscribeParams, request: Request, last_event_id: str | None = Header(None, alias="Last-Event-ID")):
    if not get_thread(thread_id):
        raise HTTPException(404, "Thread não encontrada.")
    cursor = _cursor(body.since, last_event_id)
    requested = set(body.channels)

    def allowed(row: dict) -> bool:
        method = str(row["method"])
        channel = method.split(".", 1)[0]
        if "*" not in requested and method not in requested and channel not in requested:
            return False
        namespace = row.get("namespace") or []
        if body.namespaces and namespace not in body.namespaces:
            return False
        return body.depth is None or len(namespace) <= body.depth

    async def source():
        sent = cursor
        last_heartbeat = asyncio.get_running_loop().time()
        while not await request.is_disconnected():
            rows = thread_stream_events(thread_id, sent)
            for row in rows:
                sent = int(row["seq"])
                if not allowed(row):
                    continue
                payload = json.dumps(_protocol_event(row), ensure_ascii=False, separators=(",", ":"))
                yield f"id: {sent}\nevent: message\ndata: {payload}\n\n"
            now = asyncio.get_running_loop().time()
            if now - last_heartbeat >= 15:
                yield ": heartbeat\n\n"
                last_heartbeat = now
            await asyncio.sleep(.2)

    return StreamingResponse(source(), media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Content-Encoding": "identity"})


async def _ag_ui_run(thread_id: UUID, body: AGUIRunRequest, request: Request, last_event_id: str | None = None):
    """AG-UI-compatible durable run stream for CopilotKit clients."""
    if not get_thread(thread_id): raise HTTPException(404, "Thread não encontrada.")
    resume_value = body.resume
    resume_cursor = 0
    pending = _pending_run(thread_id) if resume_value else None
    if resume_value:
        if not pending:
            raise HTTPException(409, "Não há interrupt pendente nesta thread.")
        decision = _agui_resume_decision(resume_value)
        resume_approval(pending["id"], decision)
        append_lifecycle_event(pending["id"], "queued")
        # Do not replay the previous RUN_FINISHED(interrupt) when the client
        # resumes. Start after the durable log tail that existed before the
        # decision; new worker events will then be streamed normally.
        existing = thread_stream_events(thread_id, 0)
        resume_cursor = max((int(item["seq"]) for item in existing), default=0)
        execution = {"id": pending["id"]}
        # A resume request has no new user message.  An empty current user is
        # intentionally not appended to the checkpoint snapshot.
        human = {"id": f"amp-resume-{body.run_id or uuid4()}", "content": ""}
    else:
        messages = body.messages or (body.input.get("messages", []) if isinstance(body.input, dict) else [])
        human = next((message for message in reversed(messages) if message.get("role") in {"user", "human"}), None)
        if not human: raise HTTPException(422, "AG-UI requer uma mensagem user.")
        content = _agui_text(human.get("content", ""))
        from .app import enqueue_message
        execution = enqueue_message(conversation_id=thread_id, content=str(content).strip(), source="ui", request_id=str(uuid4()), idempotency_key=str(uuid4()), deadline_seconds=None, reply_channel=None, priority=0)["execution"]
        append_lifecycle_event(execution["id"], "queued")
    async def source():
        cursor = max(_cursor(None, last_event_id), resume_cursor); active_message_id: str | None = None
        pending_interrupt: dict[str, Any] | None = None
        client_run_id = body.run_id or str(execution["id"])
        yield f"data: {json.dumps({'type': 'RUN_STARTED', 'threadId': str(thread_id), 'runId': client_run_id}, ensure_ascii=False, separators=(',', ':'))}\n\n"
        # CopilotKit owns its rendered transcript.  Seed it from the canonical
        # LangGraph checkpoint so selecting/reloading a durable thread never
        # falls back to the old amp.messages transcript.
        snapshot = await request.app.state.langgraph_graph.aget_state({"configurable": {"thread_id": str(thread_id)}})
        values = getattr(snapshot, "values", None) or {}
        yield f"data: {json.dumps({'type': 'MESSAGES_SNAPSHOT', 'messages': _agui_messages(values if isinstance(values, dict) else {}, human)}, ensure_ascii=False, separators=(',', ':'))}\n\n"
        while not await request.is_disconnected():
            for row in thread_stream_events(thread_id, cursor):
                cursor = int(row["seq"])
                if str(row["run_id"]) != str(execution["id"]): continue
                if row.get("method") == "input.requested":
                    raw = (row.get("params") or {}).get("data")
                    if isinstance(raw, dict):
                        pending_interrupt = raw
                elif row.get("method") in {"values", "updates"}:
                    row_params = row.get("params") or {}
                    snapshot_data = row_params.get("data")
                    interrupts = row_params.get("interrupts")
                    if interrupts is None and isinstance(snapshot_data, dict):
                        interrupts = snapshot_data.get("interrupts")
                    if isinstance(interrupts, list) and interrupts:
                        raw = interrupts[-1]
                        if isinstance(raw, str):
                            match = re.match(r"^Interrupt\(value=(.*), id=(['\"])(.*?)\2\)$", raw)
                            if match:
                                try:
                                    raw = {"id": match.group(3), "value": ast.literal_eval(match.group(1))}
                                except (SyntaxError, ValueError):
                                    raw = {"id": match.group(3), "value": {}}
                        # If the repr contains nested quotes that cannot be
                        # literal-evaluated (or a serializer reduced value to
                        # null), recover the tool call arguments from the same
                        # checkpoint snapshot.
                        if isinstance(raw, dict) and not raw.get("value"):
                            for message in reversed(snapshot_data.get("messages", [])):
                                if not isinstance(message, dict):
                                    continue
                                calls = message.get("tool_calls") or []
                                if not calls:
                                    continue
                                call = calls[-1] if isinstance(calls[-1], dict) else {}
                                name = call.get("name") or "ferramenta"
                                arguments = call.get("args") or {}
                                raw["value"] = {
                                    "type": "approval",
                                    "action": name,
                                    "tool": name,
                                    "arguments": arguments,
                                    "summary": f"Aprovar a execução de {name}?",
                                    "allowed_decisions": ["approve", "reject", "edit"],
                                }
                        if isinstance(raw, dict):
                            pending_interrupt = {
                                "interrupt_id": raw.get("id"),
                                "payload": raw.get("value", raw),
                            }
                events = _agui_event(
                    row,
                    thread_id=thread_id,
                    client_run_id=client_run_id,
                    active_message_id=active_message_id,
                    pending_interrupt=pending_interrupt,
                )
                if events and events[0].get("type") == "TEXT_MESSAGE_START": active_message_id = events[0]["messageId"]
                if events and events[-1].get("type") == "TEXT_MESSAGE_END": active_message_id = None
                terminal = any(event.get("type") in {"RUN_FINISHED", "RUN_ERROR"} for event in events)
                for event in events:
                    yield f"data: {json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n"
                # Do not leave the HTTP response open after the durable
                # lifecycle has reached a terminal state. CopilotKit may keep
                # its transport heartbeat alive otherwise and display a run
                # as active after the model has already finished.
                if terminal:
                    return
            await asyncio.sleep(.2)
    return StreamingResponse(source(), media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


@router.post("/threads/{thread_id}/ag-ui")
async def ag_ui_run(thread_id: UUID, body: AGUIRunRequest, request: Request, last_event_id: str | None = Header(None, alias="Last-Event-ID")):
    """Direct AG-UI endpoint, useful for diagnostics and non-Copilot clients."""
    return await _ag_ui_run(thread_id, body, request, last_event_id)


@router.post("/ag-ui")
async def ag_ui_runtime(body: AGUIRunRequest, request: Request, last_event_id: str | None = Header(None, alias="Last-Event-ID")):
    """Static AG-UI endpoint used by the CopilotKit BFF runtime.

    CopilotKit's HttpAgent receives the selected thread in the AG-UI payload;
    keeping this URL static prevents a browser-side token or dynamic upstream
    route from being necessary.
    """
    if not body.thread_id:
        raise HTTPException(422, "threadId é obrigatório para AG-UI.")
    return await _ag_ui_run(body.thread_id, body, request, last_event_id)

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
        append_lifecycle_event(execution_id, "queued")
    try: cursor = max(0, int(last_event_id or 0))
    except ValueError as exc: raise HTTPException(422, "Last-Event-ID inválido.") from exc
    return StreamingResponse(_stream(execution_id, cursor, request), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@router.post("/threads/{thread_id}/runs/{run_id}/cancel")
def cancel(thread_id: UUID, run_id: UUID, body: CancelRequest | None = None):
    if not get_thread(thread_id): raise HTTPException(404, "Thread não encontrada.")
    result = request_cancel(run_id, (body or CancelRequest()).reason, {"type": "ui"})
    if not result.get("found"): raise HTTPException(404, "Run não encontrado.")
    if result.get("status") == "cancelled": append_lifecycle_event(run_id, "completed", status="cancelled")
    return {"run_id": str(run_id), **result}

@router.post("/threads/{thread_id}/runs/{run_id}/retry", status_code=202)
def retry(thread_id: UUID, run_id: UUID):
    original = get_execution_input(run_id)
    if not original or original.get("conversation_id") != thread_id: raise HTTPException(404, "Run não encontrado.")
    from .app import enqueue_message
    result = enqueue_message(conversation_id=thread_id, content=original["content"], source="ui", request_id=str(uuid4()), idempotency_key=str(uuid4()), deadline_seconds=None, reply_channel=None, priority=0)
    append_lifecycle_event(result["execution"]["id"], "queued")
    return _run(result["execution"])
