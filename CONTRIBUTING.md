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
- `make ci`

## Pull Requests

PRs should explain:

- the issue being solved
- the implementation approach
- validation that was run
- any follow-up work or known limitations
