# Releasing

Cellin uses a semver library release model with a stable tag channel and a manual prerelease channel.

## Planning

- Delivery planning stays on the calendar milestone train, for example `2026-04`.
- Git tags use `vX.Y.Z` for stable releases and `vX.Y.ZrcN`, `vX.Y.ZbN`, or `vX.Y.ZaN` for prereleases.
- Python package versions use the same value without the leading `v`.
- Use `release-candidate` for work intended for the next cut and `release-blocker` for issues that must land before a stable release.

## Local Validation

Run these commands before creating or approving a release:

1. `make ci`
2. `make package-smoke`
3. `make release-smoke`

`make package-smoke` builds the wheel and sdist, runs `twine check`, installs the wheel into a fresh virtualenv, and verifies the installed CLI entrypoint.
`make version-check` validates that the package version surface is internally consistent and, when provided, matches the intended release tag.

## Stable Release Path

Stable library releases are tag-driven and publish to both GitHub Releases and PyPI.

1. Ensure the target commit is on `main`.
2. Create and push a semver tag such as `v0.1.0`.
3. GitHub Actions runs `.github/workflows/release.yml`.
4. The workflow validates that the tag matches the package version, runs `make release-smoke`, and uploads wheel plus sdist artifacts.
5. The workflow publishes a GitHub Release with generated notes and publishes the package distributions to PyPI.

## Prerelease Path

Prereleases are workflow-dispatch driven through `.github/workflows/rolling-release.yml`.

1. Commit a prerelease package version such as `0.2.0rc1` on the target branch or release branch.
2. Open the `rolling-release` workflow in GitHub Actions.
3. Provide the same prerelease version without the leading `v`, for example `0.2.0rc1`.
4. Provide the `target_ref` to release from, usually `main` or a release branch.
5. The workflow validates that the input matches the committed package version, then publishes a GitHub prerelease and the package distributions to PyPI.

## Trusted Publishing Setup

Cellin's publish jobs are designed for PyPI trusted publishing with GitHub OIDC.

Configure these trusted publishers on PyPI before the first live publish:

- stable publisher:
  - repository: `ben-ranford/cellin`
  - workflow: `.github/workflows/release.yml`
  - environment: `pypi`
- prerelease publisher:
  - repository: `ben-ranford/cellin`
  - workflow: `.github/workflows/rolling-release.yml`
  - environment: `pypi-prerelease`

The GitHub repository does not need long-lived `PYPI_API_TOKEN` secrets when trusted publishing is configured correctly.

## Library Metadata

The package metadata is built from `pyproject.toml` plus `src/cellin/__about__.py`.
Use `src/cellin/__about__.py` as the single source of truth for the package version.

Before the first public PyPI release, decide and add an explicit project license file if Cellin is intended for third-party reuse.

## Remote Enforcement

Default-branch enforcement is defined in `.github/rulesets/default-branch-release-grade.json`.
The required merge gates are:

- `verify`
- `package-smoke`

Changes to the release workflow or merge gates should update that tracked ruleset file and the remote GitHub ruleset together.
