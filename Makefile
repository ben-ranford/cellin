UV ?= python3 -m uv
TAG ?=
EXPECT_VERSION ?=
RELEASE_KIND ?= any

.PHONY: bootstrap hooks fmt fmt-check lint typecheck test coverage eval-smoke eval-full eval package package-smoke version-check release-smoke verify ci docs

bootstrap:
	$(UV) sync --dev
	$(UV) run lefthook install

hooks:
	$(UV) run lefthook install

fmt:
	$(UV) run ruff format src tests docs scripts

fmt-check:
	$(UV) run ruff format --check src tests docs scripts

lint:
	$(UV) run ruff check src tests docs scripts

typecheck:
	$(UV) run mypy src

test:
	$(UV) run pytest

coverage:
	$(UV) run pytest --cov=src/cellin --cov-report=term-missing:skip-covered --cov-report=json:coverage.json
	$(UV) run python scripts/check_coverage.py --coverage-json coverage.json --source-root src/cellin --overall 98 --package 98

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
		expected_version=$$(python3 scripts/release/verify_version.py --print-version); \
		"$$tmpdir/venv/bin/cellin" --version | grep -q "$$expected_version"; \
		"$$tmpdir/venv/bin/cellin" plugin list | grep -q "in-memory-trace-sink"; \
		rm -rf "$$tmpdir"

version-check:
	$(UV) run python scripts/release/verify_version.py $(if $(TAG),--tag $(TAG),) $(if $(EXPECT_VERSION),--expect-version $(EXPECT_VERSION),) --release-kind $(RELEASE_KIND)

release-smoke: ci package-smoke

verify: fmt-check lint typecheck coverage eval-smoke

ci: verify docs version-check

docs:
	$(UV) run mkdocs build --strict
