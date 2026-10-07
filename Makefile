.PHONY: check test seed run stop migrate

check:
	ruff check .
	black --check api worker migrations tests/security/test_auth.py tests/worker
	mypy services api worker --ignore-missing-imports

test:
	pytest tests/

migrate:
	alembic upgrade head

seed:
	python generator/generate.py --seed 20260906

run:
	docker compose up -d

stop:
	docker compose down