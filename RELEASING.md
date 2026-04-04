# Releasing

Cellin uses a release-grade split between stable semver tags and manual prereleases.

## Planning

- Delivery planning stays on the calendar milestone train, for example `2026-04`.
- External release artifacts are cut from semver tags such as `v0.1.0` or `v0.2.0-rc.1`.
- Use `release-candidate` for work intended for the next cut and `release-blocker` for issues that must land before a stable release.

## Local Validation

Run these commands before creating or approving a release:

1. `make ci`
2. `make package-smoke`
3. `make release-smoke`

`make package-smoke` builds the wheel and sdist, runs `twine check`, installs the wheel into a fresh virtualenv, and verifies the installed CLI entrypoint.

## Stable Release Path

Stable releases are tag-driven.

1. Ensure the target commit is on `main`.
2. Create and push a semver tag such as `v0.1.0`.
3. GitHub Actions runs `.github/workflows/release.yml`.
4. The workflow runs `make release-smoke`, attaches built artifacts plus `SHA256SUMS.txt`, and publishes a GitHub Release with generated notes.

## Prerelease Path

Prereleases are workflow-dispatch driven through a dedicated rolling channel workflow.

1. Open the `rolling-release` workflow in GitHub Actions.
2. Provide `version` without the leading `v`, for example `0.2.0-rc.1`.
3. Provide the `target_ref` to release from, usually `main` or a release branch.
4. Run the workflow to create the tag and publish a prerelease with the same artifact bundle as a stable release.

## Remote Enforcement

Default-branch enforcement is defined in `.github/rulesets/default-branch-release-grade.json`.
The required merge gates are:

- `verify`
- `package-smoke`

Changes to the release workflow or merge gates should update that tracked ruleset file and the remote GitHub ruleset together.
