.PHONY: install run worker test lint typecheck migrate revision openapi up down

install:
	pip install -e ".[dev]"

run:
	uvicorn app.main:app --reload --port 8000

worker:
	arq app.workers.settings.WorkerSettings

test:
	pytest -q

lint:
	ruff check . && ruff format --check .

typecheck:
	mypy app

migrate:
	alembic upgrade head

revision:
	alembic revision --autogenerate -m "$(m)"

openapi:
	python scripts/dump_openapi.py

up:
	docker compose up -d --build

down:
	docker compose down
