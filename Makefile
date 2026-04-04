UV ?= python3 -m uv

.PHONY: bootstrap hooks fmt fmt-check lint typecheck test eval-smoke eval-full eval package package-smoke release-smoke verify ci docs

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
	$(UV) run python -m cellin.evals smoke --output eval-results/smoke.json

eval-full:
	$(UV) run python -m cellin.evals full --output eval-results/full.json

eval: eval-full

package:
	rm -rf dist build
	$(UV) run python -m build

package-smoke: package
	$(UV) run twine check --strict dist/*
	tmpdir=$$(mktemp -d); \
	python3 -m venv "$$tmpdir/venv"; \
	"$$tmpdir/venv/bin/pip" install --upgrade pip >/dev/null; \
	"$$tmpdir/venv/bin/pip" install dist/*.whl >/dev/null; \
	"$$tmpdir/venv/bin/cellin" plugin list | grep -q "in-memory-trace-sink"; \
	rm -rf "$$tmpdir"

release-smoke: ci package-smoke

verify: fmt-check lint typecheck test eval-smoke

ci: verify docs

docs:
	$(UV) run mkdocs build --strict
