# Platform API

API administrativa inicial do Control Plane. Expõe apenas um health check nesta fase; registries,
identidade e persistência serão adicionados pelos issues subsequentes.

```bash
uv run --package amp-platform-api uvicorn amp_platform_api.main:app --reload
```
