ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim
ARG PACKAGE
ARG MODULE
ENV AMP_PACKAGE=${PACKAGE} AMP_MODULE=${MODULE} HOME=/tmp UV_CACHE_DIR=/tmp/uv-cache
WORKDIR /workspace
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /bin/
COPY . .
RUN test -n "$AMP_PACKAGE" && uv sync --frozen --no-dev --package "$AMP_PACKAGE"
USER 65532:65532
CMD ["sh", "-c", ".venv/bin/uvicorn $AMP_MODULE:app --host 0.0.0.0 --port 8000"]
