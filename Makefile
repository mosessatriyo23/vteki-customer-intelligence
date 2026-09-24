.PHONY: check test seed run stop migrate

check:
	ruff check .
	black --check .
	mypy services api

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