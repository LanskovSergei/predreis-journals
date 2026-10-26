.PHONY: install run worker consumer test lint typecheck migrate revision openapi types up down dev-stack e2e load-seed bench audit-check replay

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

consumer:
	python -m app.workers.consumer

types:
	python scripts/dump_openapi.py
	npx --yes openapi-typescript@7 docs/openapi.json -o docs/frontend/api.d.ts

dev-stack:
	python -m tools.dev_stack

e2e:
	JOURNALS_E2E=1 pytest tests/e2e -q

load-seed:
	python scripts/load_seed.py

bench:
	python scripts/bench.py

audit-check:
	python -m app.maintenance.verify_audit

replay:
	python -m app.workers.replay --dry-run
