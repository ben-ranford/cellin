# Releasing

Cellin uses a semver library release model with an automated stable channel and a manual prerelease channel.

## Planning

- Delivery planning stays on the calendar milestone train, for example `2026-04`.
- Git tags use `vX.Y.Z` for stable releases and `vX.Y.ZrcN`, `vX.Y.ZbN`, or `vX.Y.ZaN` for prereleases.
- Python package versions use the same value without the leading `v`.
- Use `release-candidate` for work intended for the next cut and `release-blocker` for issues that must land before a stable release.
- Stable semver increments are inferred from Conventional Commit types in merged PR titles and commits:
  - `fix:` maps to a patch release
  - `feat:` maps to a minor release
  - `!` or `BREAKING CHANGE:` maps to a major release

## Local Validation

Run these commands before creating or approving a release:

1. `make ci`
2. `make package-smoke`
3. `make release-smoke`

`make package-smoke` builds the wheel and sdist, runs `twine check`, installs the wheel into a fresh virtualenv, and verifies the installed CLI entrypoint.
`make version-check` validates that the package version surface is internally consistent and, when provided, matches the intended release tag.

## Stable Release Path

Stable library releases are managed by `release-please` and publish to both GitHub Releases and PyPI.

1. Merge conventional commits to `main`.
2. GitHub Actions runs `.github/workflows/release-please.yml`.
3. `release-please` opens or updates a release PR that contains the semver bump, changelog entries, and version file updates.
4. Merge the release PR after `make release-smoke` is green.
5. `release-please` tags the merge commit, creates the GitHub Release, and triggers `.github/workflows/release.yml`.
6. The release workflow validates that the tag matches the package version, runs `make release-smoke`, uploads the wheel plus sdist artifacts, attaches them to the GitHub Release, and publishes the package to PyPI.

If `v0.1.1` has not been published yet, cut that bootstrap release manually before relying on `release-please` for the next stable version.

## Prerelease Path

Prereleases are workflow-dispatch driven through `.github/workflows/rolling-release.yml`.

1. Commit a prerelease package version such as `0.2.0rc1` on the target branch or release branch.
2. Open the `rolling-release` workflow in GitHub Actions.
3. Provide the same prerelease version without the leading `v`, for example `0.2.0rc1`.
4. Provide the `target_ref` to release from, usually `main` or a release branch.
5. The workflow validates that the input matches the committed package version, then publishes a GitHub prerelease and the package distributions to PyPI.

## Trusted Publishing Setup

Cellin's release automation uses both GitHub and PyPI credentials:

- `RELEASE_PLEASE_TOKEN` in GitHub Actions for automated release PR creation, tagging, and downstream workflow triggering
- PyPI trusted publishing with GitHub OIDC for package upload

Configure `RELEASE_PLEASE_TOKEN` as a repository secret before enabling automated stable releases. Use a dedicated fine-grained GitHub token for `ben-ranford/cellin` with:

- repository permissions: `Contents` write, `Pull requests` write, `Issues` write, `Metadata` read

If you use a classic personal access token instead, it needs `repo` and `workflow`.

The default `GITHUB_TOKEN` is not sufficient here because release PRs and tags created by that token do not trigger the downstream release workflow.

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

The package metadata is built from `pyproject.toml`, `LICENSE`, and `src/cellin/__about__.py`.
Use `src/cellin/__about__.py` as the single source of truth for the package version.
The version assignment includes the inline `# x-release-please-version` annotation so `release-please` can update it automatically.

## Remote Enforcement

Default-branch enforcement is defined in `.github/rulesets/default-branch-release-grade.json`.
The required merge gates are:

- `verify`
- `package-smoke`

Changes to the release workflow or merge gates should update that tracked ruleset file and the remote GitHub ruleset together.
