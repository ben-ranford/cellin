# Feature Flags

Cellin uses feature flags when a capability is useful to test but not ready to
be treated as stable behavior in every artifact.

## Lifecycle States

Feature defaults depend on both the feature lifecycle and the release channel.

| Lifecycle | Meaning | Stable release default | Rolling build default |
| --- | --- | --- | --- |
| `preview` | Available for opt-in validation, still allowed to change | Disabled unless a reviewed release lock enables it | Enabled |
| `stable` | Supported behavior and compatibility expectations apply | Enabled | Enabled |
| `done` | Completed rollout kept in the registry for history | Enabled | Enabled |

Stable artifacts ship preview feature code so users can opt in without a
separate package. The code is left off by default unless the source-controlled
release lock enables that feature for a specific release.

Rolling builds set `CELLIN_RELEASE_CHANNEL=rolling`, so all registered flags are
enabled by default. Use rolling builds to validate preview behavior before it is
graduated.

## Listing Flags

Use the CLI to inspect registered features and their current default state:

```bash
cellin features list
cellin features list --format json
```

The `CODE` column is the immutable maintainer-facing identifier. The `NAME`
column is the activation name used by CLI flags and workspace config.

## Opting In

Enable preview features with the global CLI flag before the subcommand:

```bash
cellin --enable-feature preview-search retrieve \
  --config ./cellin.json \
  --query "memory graph retrieval"
```

Disable a feature for troubleshooting the same way:

```bash
cellin --disable-feature preview-search ingest \
  --config ./cellin.json \
  --input ./seed_envelopes.json
```

For repeatable workspace behavior, use the `features` key in `cellin.json`:

```json
{
  "features": {
    "enable": ["preview-search"],
    "disable": ["experimental-ranker"]
  }
}
```

Command-line settings override workspace settings for that invocation. A feature
name cannot appear in both `enable` and `disable`.

## Release Locks

Stable release PRs include a reviewed `features.release.lock.json` file. It can
temporarily enable preview features by immutable code:

```json
{ "release": "v0.5.0", "defaultOn": ["CELN-FEAT-0001"], "notes": { "CELN-FEAT-0001": "Required for the release smoke path." } }
```

Release locks are source-controlled and reviewed. CI validates that locked codes
exist and still point to preview features. The lock is ignored by rolling builds.

## Graduation

Merging a feature PR is not graduation. A preview feature graduates only through
a separate reviewed source change that updates the registry lifecycle after the
feature has tests, docs, compatibility notes, and rollback notes.

