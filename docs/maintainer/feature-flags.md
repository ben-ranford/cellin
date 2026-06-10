# Feature Flag Maintenance

Feature flags protect users from incomplete or risky behavior while still
allowing maintainers to ship preview code for real validation.

## When to Gate Work

Gate new work when it changes user-visible behavior, introduces a risky dream or
retrieval strategy, exposes an incomplete workflow, changes storage or release
semantics, or adds a preview capability that needs feedback before becoming
stable.

Small internal refactors and regression fixes usually do not need a new flag
unless they intentionally alter behavior.

## Allocating Codes

Every feature has an immutable `CELN-FEAT-NNNN` code and a human-readable
activation name. Allocate the next code with:

```bash
make feature-flag NAME=preview-search
```

The target calls:

```bash
uv run python scripts/add_feature_flag.py --name preview-search
```

The helper appends a preview entry to `src/cellin/features/registry.py`, using
the next sequential code such as `CELN-FEAT-0001`. Edit the generated
description before review if the default text is not clear enough.

Run the registry validator after editing:

```bash
make feature-registry-check
```

Registry rules:

- Codes are never reused or renamed.
- Active `preview` and `stable` feature names must be unique.
- `done` entries stay in the registry for history and release reporting.
- Lifecycle values are `preview`, `stable`, and `done`.

## Activation Surfaces

Users activate by feature name:

```bash
cellin --enable-feature preview-search retrieve --config ./cellin.json --query "atlas"
```

Workspace config uses the same names:

```json
{
  "features": {
    "enable": ["preview-search"],
    "disable": []
  }
}
```

Release locks use immutable codes:

```json
{
  "release": "v0.5.0",
  "defaultOn": ["CELN-FEAT-0001"],
  "notes": {
    "CELN-FEAT-0001": "Default-on for the stable release smoke path."
  }
}
```

## Release Lock Review

`features.release.lock.json` is reviewed source, not generated state. CI
validates it on every PR and rejects unknown codes, duplicate codes, unknown
top-level keys, and attempts to default-on non-preview features.

Release PR automation appends a feature flag report that separates:

- Stable by default
- Preview available by opt-in
- Preview locked default-on for this release
- Newly added preview flags since the previous release

Maintainers decide whether any preview feature should be locked on for a stable
release. Rolling builds ignore the release lock and enable all registered flags.

## Graduation Criteria

Feature PR merge is not graduation. Keep new flags in `preview` until a separate
reviewed graduation PR proves the behavior is ready.

Before changing a feature to `stable` or `done`, the graduation PR must include:

- Tests that cover the stable behavior and failure modes
- User-facing docs or examples for the behavior
- Compatibility notes for existing configs, data, CLI output, and APIs
- Rollback notes that explain how to disable or revert the behavior
- Confirmation that no release lock is carrying the feature as a temporary
  default-on exception

Use `stable` when the flag still describes supported runtime behavior. Use
`done` when the rollout is complete and the flag no longer needs user-facing
activation, but the code should remain available for history and reports.

