import os

from langchain_ollama import ChatOllama

from ..config.settings import RUNTIME_MODEL_TIMEOUT_SECONDS


OLLAMA_BASE_URL = os.getenv(
    "OLLAMA_BASE_URL",
    "http://localhost:11434",
).rstrip("/")

FAST_MODEL = "qwen3.5:2b-q4_K_M"
SMART_MODEL = "qwen3.5:4b"


def get_router_model() -> ChatOllama:
    """
    Router extremamente barato.

    Ele só precisa responder:
    fast
    ou
    smart
    """
    return ChatOllama(
        model=FAST_MODEL,
        base_url=OLLAMA_BASE_URL,
        temperature=0,
        num_predict=5,
        reasoning=False,
        client_kwargs={"timeout": RUNTIME_MODEL_TIMEOUT_SECONDS},
    )


def get_fast_model() -> ChatOllama:
    """
    Perfil FAST.

    Benchmark atual:
    ~12 tok/s
    """
    return ChatOllama(
        model=FAST_MODEL,
        base_url=OLLAMA_BASE_URL,
        temperature=0,
        num_predict=160,
        reasoning=False,
        client_kwargs={"timeout": RUNTIME_MODEL_TIMEOUT_SECONDS},
    )


def get_smart_model() -> ChatOllama:
    return ChatOllama(
        model=SMART_MODEL,
        base_url=OLLAMA_BASE_URL,
        reasoning=False,
        client_kwargs={"timeout": RUNTIME_MODEL_TIMEOUT_SECONDS},
    )
