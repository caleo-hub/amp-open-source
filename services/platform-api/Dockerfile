FROM python:3.12-slim AS runtime
ENV HOME=/tmp UV_CACHE_DIR=/tmp/uv-cache
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /bin/
COPY . /workspace
WORKDIR /workspace
RUN uv sync --frozen --no-dev --package amp-platform-api
USER 65532:65532
EXPOSE 8000
CMD [".venv/bin/uvicorn", "amp_platform_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
