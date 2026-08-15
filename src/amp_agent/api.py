import logging
import os
import time
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from .graph import graph


logger = logging.getLogger(__name__)

app = FastAPI(
    title="AMP Agent API",
    description="API local para executar o agente AMP",
    version="0.2.0",
)


# ---------------------------------------------------------------------
# Configuração do canal de voz
# ---------------------------------------------------------------------

VOICE_API_KEY_PATH = Path("/run/secrets/amp_voice_api_key")


def load_voice_api_key() -> str | None:
    try:
        return VOICE_API_KEY_PATH.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return os.getenv("AMP_VOICE_API_KEY")


VOICE_API_KEY = load_voice_api_key()

VOICE_MAX_AGE_SECONDS = 60

# Proteção simples contra replay.
# Nesta primeira versão fica em memória.
_seen_voice_requests: dict[str, float] = {}


# ---------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str


class ChatRequest(BaseModel):
    message: str = Field(
        min_length=1,
        max_length=4000,
        description="Mensagem enviada ao agente",
    )


class ChatResponse(BaseModel):
    execution_id: str
    response: str
    profile: str
    elapsed_seconds: float


class VoiceRequest(BaseModel):
    text: str = Field(
        min_length=1,
        max_length=300,
        description="Texto reconhecido pela Alexa",
    )

    source: str = Field(
        default="alexa",
        max_length=30,
    )

    request_id: str = Field(
        min_length=8,
        max_length=100,
    )

    timestamp: int


class VoiceResponse(BaseModel):
    ok: bool
    speech: str
    execution_id: str | None = None


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def cleanup_seen_voice_requests(now: float) -> None:
    expired = [
        request_id
        for request_id, created_at in _seen_voice_requests.items()
        if now - created_at > VOICE_MAX_AGE_SECONDS
    ]

    for request_id in expired:
        _seen_voice_requests.pop(request_id, None)


def validate_voice_security(
    request: VoiceRequest,
    api_key: str | None,
) -> None:
    if not VOICE_API_KEY:
        logger.error("AMP_VOICE_API_KEY não configurada")

        raise HTTPException(
            status_code=503,
            detail="Canal de voz não configurado.",
        )

    if api_key != VOICE_API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Não autorizado.",
        )

    now = time.time()

    # Evita requisições antigas ou timestamps muito no futuro.
    if abs(now - request.timestamp) > VOICE_MAX_AGE_SECONDS:
        raise HTTPException(
            status_code=401,
            detail="Requisição expirada.",
        )

    cleanup_seen_voice_requests(now)

    if request.request_id in _seen_voice_requests:
        raise HTTPException(
            status_code=409,
            detail="Requisição já processada.",
        )

    _seen_voice_requests[request.request_id] = now


def is_allowed_voice_command(text: str) -> bool:
    normalized = text.lower().strip()

    allowed_phrases = (
        "como está o servidor",
        "como esta o servidor",
        "status do servidor",
        "qual o status do servidor",
        "verifique o servidor",
        "como está o amp",
        "como esta o amp",
        "status do amp",
    )

    return normalized in allowed_phrases


# ---------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------

@app.get(
    "/health",
    response_model=HealthResponse,
)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
    )


@app.post(
    "/chat",
    response_model=ChatResponse,
)
def chat(request: ChatRequest) -> ChatResponse:
    execution_id = str(uuid4())
    started_at = time.perf_counter()

    try:
        result = graph.invoke(
            {
                "messages": [
                    HumanMessage(
                        content=request.message.strip()
                    )
                ],
                "profile": "fast",
            }
        )

        elapsed = time.perf_counter() - started_at

        response_message = result["messages"][-1]
        profile = result["profile"]

        return ChatResponse(
            execution_id=execution_id,
            response=str(response_message.content),
            profile=profile,
            elapsed_seconds=round(elapsed, 3),
        )

    except Exception:
        elapsed = time.perf_counter() - started_at

        logger.exception(
            "Falha na execução %s após %.2fs",
            execution_id,
            elapsed,
        )

        raise HTTPException(
            status_code=500,
            detail={
                "message": "Falha ao executar o agente.",
                "execution_id": execution_id,
            },
        )


@app.post(
    "/voice",
    response_model=VoiceResponse,
)
def voice(
    request: VoiceRequest,
    x_amp_voice_key: str | None = Header(default=None),
) -> VoiceResponse:
    validate_voice_security(
        request=request,
        api_key=x_amp_voice_key,
    )

    if request.source != "alexa":
        raise HTTPException(
            status_code=403,
            detail="Origem não permitida.",
        )

    if not is_allowed_voice_command(request.text):
        return VoiceResponse(
            ok=False,
            speech=(
                "Esse comando não está disponível pelo canal de voz."
            ),
        )

    execution_id = str(uuid4())

    logger.info(
        "Voice request %s: %s",
        execution_id,
        request.text,
    )

    try:
        # IMPORTANTE:
        # não passamos o texto livre da Alexa para o agente.
        # Um comando permitido vira uma instrução interna fixa.
        result = graph.invoke(
            {
                "messages": [
                    HumanMessage(
                        content=(
                            "Verifique o estado atual da API AMP e do Ollama. "
                            "Informe de forma curta se estão disponíveis "
                            "e quais modelos estão carregados."
                        )
                    )
                ],
                "profile": "fast",
            }
        )

        response_message = result["messages"][-1]

        return VoiceResponse(
            ok=True,
            speech=str(response_message.content),
            execution_id=execution_id,
        )

    except Exception:
        logger.exception(
            "Falha na execução de voz %s",
            execution_id,
        )

        return VoiceResponse(
            ok=False,
            speech=(
                "Não consegui consultar o servidor AMP neste momento."
            ),
            execution_id=execution_id,
        )