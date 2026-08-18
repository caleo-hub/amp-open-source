.PHONY: bootstrap format lint typecheck test check web-build

bootstrap:
	uv sync --all-packages --all-groups
	npm install

format:
	uv run ruff format .

lint:
	uv run ruff format --check .
	uv run ruff check .
	npm run lint

typecheck:
	uv run mypy
	npm run typecheck

test:
	uv run pytest

web-build:
	npm run build

check: lint typecheck test web-build
