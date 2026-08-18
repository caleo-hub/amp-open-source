FROM python:3.12-slim AS runtime
ENV HOME=/tmp UV_CACHE_DIR=/tmp/uv-cache
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /bin/
COPY . /workspace
WORKDIR /workspace
RUN uv sync --frozen --no-dev --package amp-example-agent
USER 65532:65532
CMD [".venv/bin/python", "-c", "from amp_example_agent import graph; print(graph.invoke({'message': 'ready'}))"]
