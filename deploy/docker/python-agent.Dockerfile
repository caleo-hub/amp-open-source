ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim
ARG PACKAGE
ARG GRAPH_MODULE
ENV AMP_PACKAGE=${PACKAGE} AMP_GRAPH_MODULE=${GRAPH_MODULE} HOME=/tmp UV_CACHE_DIR=/tmp/uv-cache
WORKDIR /workspace
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /bin/
COPY . .
RUN test -n "$AMP_PACKAGE" && uv sync --frozen --no-dev --package "$AMP_PACKAGE"
USER 65532:65532
CMD ["sh", "-c", ".venv/bin/python -c \"import importlib; importlib.import_module('$AMP_GRAPH_MODULE')\""]
