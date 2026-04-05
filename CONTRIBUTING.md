# Contributing

Thanks for contributing to Cellin.

## Development Setup

Requirements:

- Python `3.12`
- `uv`

Install dependencies, install hooks, and run the baseline validation:

```bash
make bootstrap
make release-smoke
```

`make bootstrap` installs the local git hooks through `lefthook`.
`make release-smoke` is the canonical local release gate. It runs formatting checks,
linting, type-checking, tests, eval smoke coverage, docs validation, version checks,
and package smoke validation.

If hooks stop firing after a dependency reset, run:

```bash
make hooks
```

Generated artifacts such as `eval-results/`, `dist/`, and `site/` should not be committed.

## Workflow

1. Create a branch for your change using `feat/<issue-number>-<slug>` or `bug/<issue-number>-<slug>`.
2. Keep work scoped to one issue stream.
3. Add or update tests, eval fixtures, docs, and starter examples when behavior changes.
4. Use Conventional Commits for commit messages and PR titles. Stable release automation derives semver bumps from `fix:`, `feat:`, and `BREAKING CHANGE` markers.
5. When squashing or merging, keep the final commit title in Conventional Commit form. `release-please` builds release PR notes from merged commit titles on `main`, not from GitHub labels, and non-conventional titles may be dropped from the generated changelog.
6. Run `make release-smoke` before pushing.
7. Open a draft PR until the stream is ready for review.

## Quality Gates

Canonical commands:

- `make fmt`
- `make lint`
- `make typecheck`
- `make test`
- `make eval-smoke`
- `make package`
- `make package-smoke`
- `make docs`
- `make version-check`
- `make release-smoke`
- `make ci`

The default pre-commit hook runs `make release-smoke`, so commits will fail if the smoke
surface regresses locally. You can run the same hook manually with:

```bash
python3 -m uv run lefthook run pre-commit
```

## Release Workflow

- Stable releases are initiated by `release-please` from merged conventional commits on `main`.
- Release PRs carry the version bump, changelog update, and tag metadata for the next stable cut.
- Release PR summaries are grouped from parsed Conventional Commit types such as `feat`, `fix`, `docs`, `refactor`, and `perf`. Issue labels like `bug`, `retrieval`, or `release-candidate` do not drive those sections.
- Prerelease versions use PEP 440 syntax such as `0.2.0rc1`.
- Manual prereleases are created through the GitHub Actions `rolling-release` workflow.
- Run `make version-check` when you change the package version or prepare a release branch.
- Run `make release-smoke` before you cut or approve a release-related change.
- Use `RELEASING.md` for the stable release PR flow, trusted publishing setup, token requirements, and artifact expectations.

## What to Include in PRs

- Problem statement and intended behavior
- Main implementation changes and why they were needed
- Validation evidence, especially `make release-smoke` and any targeted checks
- Documentation, starter-flow, or eval-fixture updates for user-facing behavior changes
- Compatibility notes, follow-up work, or known limitations

Use the PR template in `.github/PULL_REQUEST_TEMPLATE.md`.

## Reporting Bugs and Requesting Features

Use the issue templates in `.github/ISSUE_TEMPLATE/`.
Include reproduction steps, environment details, and expected versus actual behavior for bug reports.

## Project Structure

- `src/cellin/core`: domain models, retrieval factors, and plugin contracts
- `src/cellin/ingest`: artifact envelopes, built-in adapters, and canonical ingestion
- `src/cellin/retrieval` and `src/cellin/ranking`: candidate generation, weighted ranking, and bundle assembly
- `src/cellin/dreaming`: schedulers, strategies, and consolidation orchestration
- `src/cellin/evals`: deterministic smoke and full evaluation suites
- `src/cellin/runtime`: plugin registration and built-in runtime plugins
- `src/cellin/stores`: SQLite memory and graph stores plus the in-memory vector index
