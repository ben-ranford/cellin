UV ?= python3 -m uv

.PHONY: bootstrap hooks fmt fmt-check lint typecheck test eval-smoke eval verify ci docs

bootstrap:
	$(UV) sync --dev
	$(UV) run lefthook install

hooks:
	$(UV) run lefthook install

fmt:
	$(UV) run ruff format src tests docs

fmt-check:
	$(UV) run ruff format --check src tests docs

lint:
	$(UV) run ruff check src tests docs

typecheck:
	$(UV) run mypy src

test:
	$(UV) run pytest

eval-smoke:
	$(UV) run pytest tests/evals -q

eval: eval-smoke

verify: fmt-check lint typecheck test eval-smoke

ci: verify docs

docs:
	$(UV) run mkdocs build --strict
