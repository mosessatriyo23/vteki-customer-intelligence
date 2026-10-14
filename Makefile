.PHONY: check test seed seed-fixture run stop migrate

check:
	ruff check .
	black --check .
	mypy services api

test:
	pytest tests/

migrate:
	alembic upgrade head

seed:
	python generator/generate.py --seed 20260906 --as-of-date 2026-09-06

seed-fixture:
	python generator/generate.py --seed 20260906 --as-of-date 2026-09-06 --customers 2000 --output-dir fixtures/intg_v1 --ground-truth-dir generator/ground_truth/fixtures/intg_v1

run:
	docker compose up -d

stop:
	docker compose down