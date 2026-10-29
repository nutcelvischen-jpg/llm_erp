.PHONY: setup up down logs dev test test-llm test-db seed ingest eval-sql eval-rag lint

setup:
	uv venv --python 3.12 --allow-existing
	uv pip install -e ".[dev]"
	cp -n .env.example .env || true

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

dev:
	uv run uvicorn backend.app.main:app --reload --port 8000

test:
	uv run pytest -q

test-llm:
	uv run pytest -q -m llm

test-db:
	uv run pytest -q -m db

seed:
	uv run python scripts/seed_db.py

ingest:
	uv run python scripts/ingest_docs.py data/docs

eval-sql:
	uv run python scripts/eval_text2sql.py

eval-rag:
	uv run python scripts/eval_rag.py

lint:
	uv run ruff check backend scripts
