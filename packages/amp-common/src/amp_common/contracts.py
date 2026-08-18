from pydantic import BaseModel, ConfigDict


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(StrictContract):
    service: str
    status: str = "ok"


class RuntimeContext(StrictContract):
    tenant_id: str
    user_id: str
    thread_id: str
    run_id: str
