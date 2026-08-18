import base64
import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from urllib.request import urlopen
from urllib.error import URLError
from pydantic import BaseModel, Field

from ..config.settings import (
    CHAT_WAIT_TIMEOUT_SECONDS,
    REPLY_CHANNELS,
)
from ..persistence.repositories import (
    create_conversation,
    enqueue_execution,
    get_conversation,
    get_execution,
    list_messages,
    find_existing_execution,
    get_default_workspace,
    list_executions,
    list_execution_events,
)
from ..persistence.db import connection
from ..config.settings import database_settings
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres import AsyncPostgresStore
from ..persistence.runtime import request_cancel
from ..observability import (
    bind_context,
    configure_json_logging,
    configure_telemetry,
    instrument_fastapi,
    log_event,
)
from ..config.settings import HEALTH_CACHE_SECONDS, SEARXNG_BASE_URL, WORKER_STALE_SECONDS
from ..agent.models import FAST_MODEL, OLLAMA_BASE_URL


logger = logging.getLogger(__name__)
configure_json_logging()
configure_telemetry("amp-api")


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Keep native LangGraph persistence handles available to the API."""
    from ..agent.graph import build_graph
    dsn = database_settings().dsn("langgraph,public")
    async with AsyncPostgresSaver.from_conn_string(dsn) as checkpointer, AsyncPostgresStore.from_conn_string(dsn) as store:
        await checkpointer.setup()
        await store.setup()
        application.state.langgraph_checkpointer = checkpointer
        application.state.langgraph_store = store
        application.state.langgraph_graph = build_graph(checkpointer, store)
        yield


app = FastAPI(
    title="AMP Agent API",
    description="API local para executar o agente AMP",
    version="0.3.0",
    lifespan=lifespan,
)
instrument_fastapi(app)
from .chat import router as chat_router
app.include_router(chat_router)


@app.middleware("http")
async def correlation_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    with bind_context(
        request_id=request_id,
        run_id=request.headers.get("X-AMP-Run-ID"),
        assistant_id=request.headers.get("X-AMP-Assistant-ID"),
        http_method=request.method,
        http_route=request.url.path,
    ):
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

VOICE_API_KEY_PATH = Path("/run/secrets/amp_voice_api_key")
VOICE_MAX_AGE_SECONDS = 60
ALLOWED_SOURCES = {"chat", "voice", "alexa", "aws_iot", "ui"}


def load_voice_api_key() -> str | None:
    try:
        value = VOICE_API_KEY_PATH.read_text(encoding="utf-8").strip()
        return value or None
    except FileNotFoundError:
        return os.getenv("AMP_VOICE_API_KEY")


VOICE_API_KEY = load_voice_api_key()


class HealthResponse(BaseModel):
    status: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    execution_id: UUID
    response: str
    profile: str
    elapsed_seconds: float


class VoiceRequest(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    source: str = Field(default="alexa", max_length=30)
    request_id: str | None = Field(default=None, min_length=8, max_length=100)
    timestamp: int


class VoiceResponse(BaseModel):
    ok: bool
    speech: str
    execution_id: UUID | None = None
    status: Literal["accepted", "processing", "completed", "failed"] = "accepted"
    conversation_id: UUID | None = None
    request_id: str | None = None


class ConversationCreate(BaseModel):
    channel: str = Field(default="chat", min_length=1, max_length=30)


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    request_id: str | None = Field(default=None, min_length=8, max_length=120)
    source: str = Field(default="chat", min_length=1, max_length=30)
    deadline_seconds: int | None = Field(default=None, ge=1, le=600)
    reply_channel: str | None = None
    priority: int = Field(default=0, ge=-100, le=100)


class ExecutionResponse(BaseModel):
    execution_id: UUID
    conversation_id: UUID
    request_id: str | None = None
    status: str
    job_status: str | None = None
    result: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    attempts: int | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    workspace_id: UUID | None = None
    agent_id: UUID | None = None
    agent_version_id: UUID | None = None
    root_execution_id: UUID | None = None
    parent_execution_id: UUID | None = None
    cancel_requested_at: datetime | None = None
    cancel_effective_at: datetime | None = None
    effective_deadline_at: datetime | None = None
    max_steps: int | None = None
    used_steps: int | None = None
    max_tool_calls: int | None = None
    used_tool_calls: int | None = None
    error_fingerprint: str | None = None
    error_retryable: bool | None = None
    cancel_requested: bool = False


class CancelRequest(BaseModel):
    reason: Literal["user_requested", "operator_requested"] = "user_requested"


class AcceptedResponse(BaseModel):
    execution_id: UUID
    conversation_id: UUID
    request_id: str
    status: str


def cleanup_request_identity(request_id: str | None, idempotency_key: str | None) -> tuple[str, str]:
    request_id = (request_id or str(uuid4())).strip()
    idempotency_key = (idempotency_key or request_id).strip()
    if not request_id or not idempotency_key:
        raise HTTPException(status_code=422, detail="Identidade da solicitação inválida.")
    return request_id, idempotency_key


def validate_source(source: str) -> None:
    if source not in ALLOWED_SOURCES:
        raise HTTPException(status_code=422, detail="source não permitido.")


def validate_reply_channel(reply_channel: str | None) -> None:
    if reply_channel is not None and reply_channel not in REPLY_CHANNELS:
        raise HTTPException(status_code=422, detail="reply_channel não permitido.")


def serialize_execution(row: dict) -> dict:
    return {
        "execution_id": row["id"], "conversation_id": row["conversation_id"],
        "workspace_id": row.get("workspace_id"), "agent_id": row.get("agent_id"),
        "agent_version_id": row.get("agent_version_id"), "root_execution_id": row.get("root_execution_id"),
        "parent_execution_id": row.get("parent_execution_id"), "request_id": row.get("request_id"),
        "status": row["status"], "job_status": row.get("job_status"), "result": row.get("result"),
        "error_code": row.get("error_code") or row.get("last_error_code"),
        "error_message": row.get("error_message") or row.get("last_error"),
        "error_fingerprint": row.get("error_fingerprint"), "error_retryable": row.get("error_retryable"),
        "attempts": row.get("attempts"), "created_at": row.get("created_at"),
        "started_at": row.get("started_at"), "completed_at": row.get("completed_at"),
        "cancel_requested_at": row.get("cancel_requested_at"), "cancel_effective_at": row.get("cancel_effective_at"),
        "effective_deadline_at": row.get("effective_deadline_at"), "max_steps": row.get("max_steps"),
        "used_steps": row.get("used_steps"), "max_tool_calls": row.get("max_tool_calls"),
        "used_tool_calls": row.get("used_tool_calls"), "cancel_requested": bool(row.get("cancel_requested_at")),
    }


def wait_for_execution(execution_id: UUID, timeout: float) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = get_execution(execution_id)
        if not row:
            return None
        if row["status"] in {"succeeded", "failed", "cancelled"}:
            return row
        time.sleep(0.2)
    return get_execution(execution_id)


def enqueue_message(
    *,
    conversation_id: UUID,
    content: str,
    source: str,
    request_id: str | None,
    idempotency_key: str | None,
    deadline_seconds: int | None,
    reply_channel: str | None,
    priority: int,
) -> dict:
    validate_source(source)
    validate_reply_channel(reply_channel)
    request_id, idempotency_key = cleanup_request_identity(request_id, idempotency_key)
    deadline_at = None
    if deadline_seconds is not None:
        deadline_at = datetime.now(timezone.utc) + timedelta(seconds=deadline_seconds)
    try:
        result = enqueue_execution(
            source=source,
            request_id=request_id,
            idempotency_key=idempotency_key,
            conversation_id=conversation_id,
            content=content,
            channel=source,
            reply_channel=reply_channel,
            deadline_at=deadline_at,
            priority=priority,
        )
        execution = result["execution"]
        log_event(
            logger,
            "execution.accepted",
            execution_id=str(execution["id"]),
            thread_id=str(conversation_id),
            run_id=str(execution["id"]),
            assistant_id=(
                str(execution["agent_id"]) if execution.get("agent_id") else None
            ),
            source=source,
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def validate_voice_security(request: VoiceRequest, api_key: str | None) -> None:
    if not VOICE_API_KEY:
        logger.error("Chave do canal de voz não configurada")
        raise HTTPException(status_code=503, detail="Canal de voz não configurado.")
    if api_key != VOICE_API_KEY:
        raise HTTPException(status_code=401, detail="Não autorizado.")
    if abs(time.time() - request.timestamp) > VOICE_MAX_AGE_SECONDS:
        raise HTTPException(status_code=401, detail="Requisição expirada.")


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


_health_cache: tuple[float, dict] | None = None


def _health_check(name: str, check) -> dict:
    started = time.monotonic()
    try:
        detail = check()
        return {"status": "up", "duration_ms": round((time.monotonic() - started) * 1000, 2), **(detail or {})}
    except Exception as exc:
        return {"status": "down", "duration_ms": round((time.monotonic() - started) * 1000, 2), "error_code": f"{name}_unavailable", "error_class": type(exc).__name__}


def _ready_snapshot() -> dict:
    global _health_cache
    now = time.monotonic()
    if _health_cache and now - _health_cache[0] < HEALTH_CACHE_SECONDS:
        return _health_cache[1]
    def postgres():
        with connection() as conn:
            conn.execute("SELECT 1").fetchone()
        return {}
    def worker():
        with connection() as conn:
            row = conn.execute("SELECT worker_id, last_seen_at FROM amp.worker_instances ORDER BY last_seen_at DESC LIMIT 1").fetchone()
        if not row or (datetime.now(timezone.utc) - row["last_seen_at"]).total_seconds() > WORKER_STALE_SECONDS:
            raise RuntimeError("worker_stale")
        return {"worker_id": row["worker_id"]}
    def ollama():
        with urlopen(f"{OLLAMA_BASE_URL}/api/tags", timeout=2) as response:
            payload = json.loads(response.read())
        models = {item.get("name") for item in payload.get("models", []) if isinstance(item, dict)}
        missing = sorted({FAST_MODEL} - models)
        if missing: raise RuntimeError("models_missing")
        return {"models": sorted(models)}
    def searxng():
        with urlopen(f"{SEARXNG_BASE_URL.rstrip('/')}/config", timeout=2) as response:
            if response.status >= 400: raise RuntimeError("searxng_http")
        return {}
    checks = {name: _health_check(name, check) for name, check in (("postgres", postgres), ("worker", worker), ("ollama", ollama), ("searxng", searxng))}
    snapshot = {"status": "ok" if all(item["status"] == "up" for item in checks.values()) else "degraded", "checks": checks, "checked_at": datetime.now(timezone.utc).isoformat()}
    _health_cache = (now, snapshot)
    return snapshot


@app.get("/health/live")
def health_live():
    return {"status": "ok"}


@app.get("/health/ready")
def health_ready():
    snapshot = _ready_snapshot()
    return JSONResponse(status_code=200 if snapshot["status"] == "ok" else 503, content=snapshot)


@app.post("/v1/conversations", status_code=201)
def create_conversation_endpoint(request: ConversationCreate):
    return create_conversation(request.channel)


@app.post("/v1/conversations/{conversation_id}/messages", response_model=AcceptedResponse, status_code=202)
def create_message_endpoint(
    conversation_id: UUID,
    request: MessageCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if not get_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversa não encontrada.")
    result = enqueue_message(
        conversation_id=conversation_id,
        content=request.content.strip(),
        source=request.source,
        request_id=request.request_id,
        idempotency_key=idempotency_key,
        deadline_seconds=request.deadline_seconds,
        reply_channel=request.reply_channel,
        priority=request.priority,
    )
    execution = result["execution"]
    return AcceptedResponse(
        execution_id=execution["id"],
        conversation_id=execution["conversation_id"],
        request_id=execution.get("request_id") or request.request_id or str(execution["id"]),
        status=execution["status"],
    )


@app.get("/v1/executions/{execution_id}", response_model=ExecutionResponse)
def execution_endpoint(execution_id: UUID):
    row = get_execution(execution_id)
    if not row:
        raise HTTPException(status_code=404, detail="Execução não encontrada.")
    return serialize_execution(row)


@app.get("/v1/executions")
def executions_endpoint(workspace_id: UUID | None = None, status: str | None = None, limit: int = Query(default=50, ge=1, le=100), cursor: str | None = None):
    workspace = workspace_id or (get_default_workspace() or {}).get("id")
    if not workspace: raise HTTPException(status_code=503, detail="Workspace bootstrap indisponível.")
    before_created = before_id = None
    if cursor:
        try:
            decoded = json.loads(base64.urlsafe_b64decode(cursor.encode() + b"=" * (-len(cursor) % 4)))
            if decoded.get("v") != 1 or decoded.get("workspace_id") != str(workspace) or decoded.get("status") != status: raise ValueError
            before_created = datetime.fromisoformat(decoded["created_at"]); before_id = UUID(decoded["id"])
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            raise HTTPException(status_code=422, detail="Cursor inválido.")
    rows = list_executions(workspace, status, limit + 1, before_created, before_id)
    has_more = len(rows) > limit; rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        raw = {"v": 1, "workspace_id": str(workspace), "status": status, "created_at": last["created_at"].isoformat(), "id": str(last["id"])}
        next_cursor = base64.urlsafe_b64encode(json.dumps(raw, separators=(",", ":")).encode()).decode().rstrip("=")
    return {"items": [serialize_execution(row) for row in rows], "next_cursor": next_cursor, "has_more": has_more}


@app.get("/v1/executions/{execution_id}/events")
def execution_events_endpoint(execution_id: UUID, after_sequence: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=500)):
    if not get_execution(execution_id): raise HTTPException(status_code=404, detail="Execução não encontrada.")
    return list_execution_events(execution_id, after_sequence, limit)


async def _execution_event_stream(execution_id: UUID, after_sequence: int):
    cursor = after_sequence
    while True:
        page = list_execution_events(execution_id, cursor, 100)
        rows = page["items"] if isinstance(page, dict) else page
        for row in rows:
            cursor = int(row["sequence_no"])
            payload = json.dumps(row, ensure_ascii=False, default=str, separators=(",", ":"))
            yield f"id: {cursor}\nevent: {row.get('event_name', 'execution.event')}\ndata: {payload}\n\n"

        execution = get_execution(execution_id)
        if execution and execution["status"] in {"succeeded", "failed", "cancelled"}:
            break
        yield ": heartbeat\n\n"
        await asyncio.sleep(0.5)


@app.get("/v1/executions/{execution_id}/events/stream")
async def execution_events_stream_endpoint(
    execution_id: UUID,
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    after_sequence: int = Query(default=0, ge=0),
):
    if not get_execution(execution_id):
        raise HTTPException(status_code=404, detail="Execução não encontrada.")
    try:
        cursor = max(after_sequence, int(last_event_id or 0))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Last-Event-ID inválido.") from exc

    async def stream_with_disconnect_check():
        async for chunk in _execution_event_stream(execution_id, cursor):
            if await request.is_disconnected():
                break
            yield chunk

    return StreamingResponse(
        stream_with_disconnect_check(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/v1/executions/{execution_id}/cancel")
def cancel_execution_endpoint(execution_id: UUID, request: CancelRequest | None = None):
    result = request_cancel(execution_id, (request or CancelRequest()).reason, {"type": "api"})
    if not result.get("found"): raise HTTPException(status_code=404, detail="Execução não encontrada.")
    status_code = 202 if result.get("cancel_requested") else 200
    return JSONResponse(status_code=status_code, content={"execution_id": str(execution_id), **result})


@app.get("/v1/conversations/{conversation_id}/messages")
def messages_endpoint(conversation_id: UUID):
    if not get_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversa não encontrada.")
    return {"conversation_id": conversation_id, "messages": list_messages(conversation_id)}


def existing_execution_or_none(source: str, request_id: str | None, idempotency_key: str | None):
    return find_existing_execution(source, request_id, idempotency_key)


@app.post("/chat")
def chat(
    request: ChatRequest,
    conversation_header: str | None = Header(default=None, alias="X-AMP-Conversation-ID"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        conversation_id = UUID(conversation_header) if conversation_header else None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="X-AMP-Conversation-ID inválido.") from exc
    existing = existing_execution_or_none("chat", None, idempotency_key)
    if existing and conversation_id is None:
        conversation_id = existing["conversation_id"]
    if conversation_id is None:
        conversation_id = create_conversation("chat")["id"]
    elif not get_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversa não encontrada.")

    result = enqueue_message(
        conversation_id=conversation_id,
        content=request.message.strip(),
        source="chat",
        request_id=None,
        idempotency_key=idempotency_key,
        deadline_seconds=int(CHAT_WAIT_TIMEOUT_SECONDS),
        reply_channel=None,
        priority=0,
    )
    execution = result["execution"]
    final = wait_for_execution(execution["id"], CHAT_WAIT_TIMEOUT_SECONDS)
    if not final or final["status"] in {"queued", "running"}:
        return JSONResponse(
            status_code=202,
            content={
                "execution_id": str(execution["id"]),
                "conversation_id": str(conversation_id),
                "status": "pending",
            },
        )
    if final["status"] != "succeeded":
        raise HTTPException(
            status_code=500,
            detail={"execution_id": str(execution["id"]), "message": "Execução falhou."},
        )
    elapsed = 0.0
    if final.get("started_at") and final.get("completed_at"):
        elapsed = (final["completed_at"] - final["started_at"]).total_seconds()
    return ChatResponse(
        execution_id=final["id"],
        response=final["result"] or "",
        profile=final.get("model_profile") or "fast",
        elapsed_seconds=round(elapsed, 3),
    )


@app.post("/voice")
def voice(
    request: VoiceRequest,
    x_amp_voice_key: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    validate_voice_security(request, x_amp_voice_key)
    if request.source != "alexa":
        raise HTTPException(status_code=403, detail="Origem não permitida.")
    existing = existing_execution_or_none("voice", request.request_id, idempotency_key or request.request_id)
    conversation_id = (
        existing["conversation_id"]
        if existing
        else create_conversation("voice")["id"]
    )
    result = enqueue_message(
        conversation_id=conversation_id,
        content=request.text.strip(),
        source="voice",
        request_id=request.request_id,
        idempotency_key=idempotency_key or request.request_id,
        deadline_seconds=None,
        reply_channel="alexa",
        priority=100,
    )
    execution = result["execution"]
    return JSONResponse(status_code=202, content={
        "ok": True,
        "status": "accepted",
        "speech": "Entendido. Estou processando isso.",
        "execution_id": str(execution["id"]),
        "conversation_id": str(execution["conversation_id"]),
        "request_id": execution.get("request_id") or request.request_id,
    })


@app.get("/voice/executions/{execution_id}")
def voice_execution(
    execution_id: UUID,
    x_amp_voice_key: str | None = Header(default=None),
):
    if not VOICE_API_KEY:
        raise HTTPException(status_code=503, detail="Canal de voz não configurado.")
    if x_amp_voice_key != VOICE_API_KEY:
        raise HTTPException(status_code=401, detail="Não autorizado.")
    row = get_execution(execution_id)
    if not row:
        raise HTTPException(status_code=404, detail="Execução não encontrada.")
    status = row["status"]
    if status in {"queued", "running"}:
        return {"ok": True, "status": "processing", "speech": "Ainda estou processando sua solicitação.", "execution_id": str(execution_id)}
    if status == "succeeded":
        return {"ok": True, "status": "completed", "speech": row.get("result") or "", "execution_id": str(execution_id)}
    return {"ok": False, "status": "failed", "speech": "Não consegui concluir essa solicitação.", "execution_id": str(execution_id)}
