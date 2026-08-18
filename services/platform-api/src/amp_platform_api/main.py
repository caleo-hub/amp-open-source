from amp_common import HealthResponse
from fastapi import FastAPI

app = FastAPI(title="AMP Platform API", version="0.1.0")


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(service="platform-api")
