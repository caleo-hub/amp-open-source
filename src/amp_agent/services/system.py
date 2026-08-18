import json
import os
from urllib.error import URLError
from urllib.request import urlopen


OLLAMA_BASE_URL = os.getenv(
    "OLLAMA_BASE_URL",
    "http://localhost:11434",
).rstrip("/")
REQUIRED_MODELS = ("qwen3.5:2b-q4_K_M",)


def get_system_status() -> dict:
    """Return deterministic service health available to the container."""
    try:
        with urlopen(
            f"{OLLAMA_BASE_URL}/api/tags",
            timeout=3,
        ) as response:
            payload = json.loads(response.read())

        models = [
            item["name"]
            for item in payload.get("models", [])
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        ]
        ollama_available = True
    except (OSError, URLError, TimeoutError, ValueError, KeyError, TypeError):
        models = []
        ollama_available = False

    available_models = set(models)
    return {
        "health": {
            "available": ollama_available,
            "source": "container-services",
        },
        "amp_api": {
            "available": True,
        },
        "ollama": {
            "available": ollama_available,
            "models": models,
            "required_models": {
                model: model in available_models
                for model in REQUIRED_MODELS
            },
        },
    }
