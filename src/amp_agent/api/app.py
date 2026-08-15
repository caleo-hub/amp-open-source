import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..config.settings import (
    CHAT_WAIT_TIMEOUT_SECONDS,
    REPLY_CHANNELS,
    VOICE_WAIT_TIMEOUT_SECONDS,
)
from ..persistence.repositories import (
    create_conversation,
    enqueue_execution,
    get_conversation,
    get_execution,
    list_messages,
    find_existing_execution,
)


logger = logging.getLogger(__name__)
app = FastAPI(
    title="AMP Agent API",
    description="API local para executar o agente AMP",
    version="0.3.0",
)

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
    status: Literal["completed", "pending", "rejected", "failed"] = "completed"


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
        "execution_id": row["id"],
        "conversation_id": row["conversation_id"],
        "request_id": row.get("request_id"),
        "status": row["status"],
        "job_status": row.get("job_status"),
        "result": row.get("result"),
        "error_code": row.get("error_code") or row.get("last_error_code"),
        "error_message": row.get("error_message") or row.get("last_error"),
        "attempts": row.get("attempts"),
        "created_at": row.get("created_at"),
        "started_at": row.get("started_at"),
        "completed_at": row.get("completed_at"),
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
        return enqueue_execution(
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
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def is_allowed_voice_command(text: str) -> bool:
    return text.lower().strip() in {
        "como está o servidor",
        "como esta o servidor",
        "status do servidor",
        "qual o status do servidor",
        "verifique o servidor",
        "como está o amp",
        "como esta o amp",
        "status do amp",
    }


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
    if not is_allowed_voice_command(request.text):
        return VoiceResponse(
            ok=False,
            status="rejected",
            speech="Esse comando não está disponível pelo canal de voz.",
        )

    existing = existing_execution_or_none("voice", request.request_id, idempotency_key or request.request_id)
    conversation_id = (
        existing["conversation_id"]
        if existing
        else create_conversation("voice")["id"]
    )
    result = enqueue_message(
        conversation_id=conversation_id,
        content=(
            "Verifique o estado atual da API AMP e do Ollama. "
            "Informe de forma curta se estão disponíveis e quais modelos estão carregados."
        ),
        source="voice",
        request_id=request.request_id,
        idempotency_key=idempotency_key or request.request_id,
        deadline_seconds=int(VOICE_WAIT_TIMEOUT_SECONDS),
        reply_channel="alexa",
        priority=100,
    )
    execution = result["execution"]
    final = wait_for_execution(execution["id"], VOICE_WAIT_TIMEOUT_SECONDS)
    if not final or final["status"] in {"queued", "running"}:
        return JSONResponse(
            status_code=202,
            content={
                "ok": True,
                "status": "pending",
                "speech": "Solicitação recebida; a execução continua em andamento.",
                "execution_id": str(execution["id"]),
            },
        )
    if final["status"] != "succeeded":
        return VoiceResponse(
            ok=False,
            status="failed",
            speech="Não consegui concluir a consulta ao servidor AMP.",
            execution_id=execution["id"],
        )
    return VoiceResponse(
        ok=True,
        status="completed",
        speech=final["result"] or "",
        execution_id=execution["id"],
    )
