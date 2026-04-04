# Contributing

## Development Setup

1. Install Python `3.12`.
2. Install `uv`.
3. Run `make bootstrap`.

## Expected Workflow

1. Branch from `main` using `feat/<issue-number>-<slug>` or `bug/<issue-number>-<slug>`.
2. Keep work scoped to a single issue stream.
3. Run `make ci` before pushing.
4. Open a draft PR until the stream is ready for review.

## Quality Gates

The canonical checks are:

- `make fmt`
- `make lint`
- `make typecheck`
- `make test`
- `make eval-smoke`
- `make package-smoke`
- `make ci`

## Release Workflow

- Stable releases are cut from semver tags such as `v0.1.0`.
- Manual prereleases are created through the GitHub Actions `rolling-release` workflow.
- Run `make release-smoke` before you cut or approve a release-related change.
- Use the guidance in `RELEASING.md` for tag naming, release channels, and artifact expectations.

## Pull Requests

PRs should explain:

- the issue being solved
- the implementation approach
- validation that was run
- any follow-up work or known limitations
