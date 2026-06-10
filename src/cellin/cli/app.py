"""Argparse-based local CLI for Cellin."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

from cellin.__about__ import __version__
from cellin.cli.config import (
    ResolvedWorkspace,
    WorkspaceFeaturesConfig,
    append_trace,
    init_workspace,
    load_workspace,
    read_traces,
)
from cellin.core import Modality
from cellin.core.models import JSONValue
from cellin.dreaming import DreamRunner
from cellin.dreaming.models import DreamDiff
from cellin.evals import run_evaluation_suite
from cellin.features import REGISTRY, ReleaseChannel, resolve_features
from cellin.ingest import ArtifactEnvelope, CanonicalIngestor
from cellin.ranking import WeightedRanker, get_weight_profile
from cellin.retrieval import RetrievalCandidateGenerator, WeightedRetriever
from cellin.runtime import (
    InMemoryTraceSinkPlugin,
    PluginRegistry,
    StorageBundle,
    StorageRole,
    build_storage_bundle,
    list_storage_backends,
    load_storage_backends_from_entry_points,
    setup_storage_backends,
)
from cellin.runtime.storage import StorageConfig

TRACE_INSPECT_SUCCESS_EXIT_CODE = 0
STORAGE_ROLE_CHOICES = ("memory", "graph", "vector", "representation")
DEFAULT_FEATURE_LIST_FORMAT = "table"


@dataclass(frozen=True, slots=True)
class FeatureContext:
    """Resolved feature activation for the current invocation."""

    channel: ReleaseChannel
    enabled_names: tuple[str, ...]
    disabled_names: tuple[str, ...]
    resolved: dict[str, bool]

    def is_enabled(self, code: str) -> bool:
        return self.resolved.get(code, False)


def _load_envelopes(input_path: Path) -> tuple[ArtifactEnvelope, ...]:
    raw = json.loads(input_path.read_text(encoding="utf-8"))
    assert isinstance(raw, list)
    envelopes: list[ArtifactEnvelope] = []
    for item in raw:
        assert isinstance(item, dict)
        metadata = item["metadata"]
        payload = item["payload"]
        assert isinstance(metadata, dict)
        assert isinstance(payload, str | dict | list)
        envelopes.append(
            ArtifactEnvelope(
                envelope_id=str(item["envelope_id"]),
                modality=Modality(str(item["modality"])),
                payload=payload,
                source_id=str(item["source_id"]),
                source_type=str(item["source_type"]),
                observed_at=datetime.fromisoformat(str(item["observed_at"])),
                metadata=dict(metadata),
            )
        )
    return tuple(envelopes)


def _load_bundle(config_path: Path) -> tuple[ResolvedWorkspace, StorageBundle]:
    workspace = load_workspace(config_path)
    return workspace, build_storage_bundle(workspace.storage, workspace_root=config_path.parent)


def _retriever(config_path: Path) -> WeightedRetriever:
    workspace, bundle = _load_bundle(config_path)
    profile = get_weight_profile(workspace.profile_name)
    return WeightedRetriever(
        candidate_generator=RetrievalCandidateGenerator(
            bundle.memory_store,
            bundle.graph_store,
            vector_store=bundle.vector_store,
        ),
        ranker=WeightedRanker(profile=profile),
        profile=profile,
    )


def _record(config_path: Path, name: str, payload: dict[str, JSONValue]) -> None:
    append_trace(load_workspace(config_path), name=name, payload=payload)


def _release_channel() -> ReleaseChannel:
    channel = os.getenv("CELLIN_RELEASE_CHANNEL", "release")
    if channel not in {"release", "dev", "rolling"}:
        raise ValueError(f"Unknown release channel `{channel}`.")
    return cast(ReleaseChannel, channel)


def _merge_feature_names(
    config_features: WorkspaceFeaturesConfig,
    cli_enable: Sequence[str],
    cli_disable: Sequence[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    enabled = set(config_features.enable)
    disabled = set(config_features.disable)
    enabled -= set(cli_disable)
    disabled -= set(cli_enable)
    enabled.update(cli_enable)
    disabled.update(cli_disable)
    return tuple(sorted(enabled)), tuple(sorted(disabled))


def _resolve_feature_context(args: argparse.Namespace) -> FeatureContext:
    config_features = WorkspaceFeaturesConfig()
    config_path = getattr(args, "config", None)
    if isinstance(config_path, str):
        config_features = load_workspace(Path(config_path)).features

    enabled_names, disabled_names = _merge_feature_names(
        config_features,
        getattr(args, "enable_feature", ()) or (),
        getattr(args, "disable_feature", ()) or (),
    )
    channel = _release_channel()
    resolved = resolve_features(REGISTRY, channel, {}, enabled_names, disabled_names)

    return FeatureContext(
        channel=channel,
        enabled_names=enabled_names,
        disabled_names=disabled_names,
        resolved=resolved,
    )


def _feature_manifest_defaults(channel: ReleaseChannel) -> list[dict[str, object]]:
    defaults = resolve_features(REGISTRY, channel, {}, (), ())
    return [
        {
            "code": feature.code,
            "name": feature.name,
            "lifecycle": feature.lifecycle,
            "default_enabled": defaults[feature.code],
        }
        for feature in REGISTRY
    ]


def cmd_init(args: argparse.Namespace, _feature_context: FeatureContext) -> int:
    config_path = init_workspace(Path(args.workspace))
    print(f"initialized workspace config={config_path}")
    return 0


def cmd_ingest(args: argparse.Namespace, _feature_context: FeatureContext) -> int:
    config_path = Path(args.config)
    workspace = load_workspace(config_path)
    bundle = build_storage_bundle(workspace.storage, workspace_root=config_path.parent)
    ingestor = CanonicalIngestor.with_built_in_adapters(
        graph_store=bundle.graph_store,
        memory_store=bundle.memory_store,
        vector_store=bundle.vector_store,
    )
    result = ingestor.ingest_envelopes(_load_envelopes(Path(args.input)))
    _record(
        config_path,
        "cli.ingest",
        {
            "artifact_count": len(result.artifacts),
            "memory_count": len(result.memories),
            "edge_count": len(result.edges),
        },
    )
    print(
        "ingested "
        f"artifacts={len(result.artifacts)} "
        f"memories={len(result.memories)} "
        f"edges={len(result.edges)}"
    )
    return 0


def cmd_retrieve(args: argparse.Namespace, _feature_context: FeatureContext) -> int:
    config_path = Path(args.config)
    bundle = _retriever(config_path).retrieve(args.query, top_k=args.top_k)
    _record(
        config_path,
        "cli.retrieve",
        {
            "query": args.query,
            "result_count": len(bundle.memories),
            "total_score": bundle.total_score,
        },
    )
    print(f"query={bundle.query} total_score={bundle.total_score:.6f}")
    for item in bundle.memories:
        factor_summary = ", ".join(f"{factor.name}={factor.value:.3f}" for factor in item.factors)
        print(
            f"memory_id={item.memory.memory_id} "
            f"score={item.score:.6f} "
            f"text={item.memory.text} "
            f"factors=[{factor_summary}]"
        )
    return 0


def cmd_dream_run(args: argparse.Namespace, _feature_context: FeatureContext) -> int:
    config_path = Path(args.config)
    workspace = load_workspace(config_path)
    bundle = build_storage_bundle(workspace.storage, workspace_root=config_path.parent)
    runner = DreamRunner(
        graph_store=bundle.graph_store,
        memory_store=bundle.memory_store,
    )
    results = (
        (runner.run_strategy(args.strategy),) if args.strategy is not None else runner.run_pending()
    )
    completed = tuple(result for result in results if result is not None)
    for result in completed:
        _record(
            config_path,
            "cli.dream",
            {
                "strategy_name": result.artifact.strategy_name,
                "affected_count": len(result.artifact.affected_memory_ids),
            },
        )
        print(
            f"strategy={result.artifact.strategy_name} "
            f"summary={result.artifact.summary} "
            f"affected={','.join(result.artifact.affected_memory_ids)}"
        )
        if args.diff_out is not None:
            diff_path = Path(args.diff_out)
            diff_path.parent.mkdir(parents=True, exist_ok=True)
            diff_path.write_text(
                json.dumps(result.diff.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
            )
            print(f"diff written to {diff_path}")
    if not completed:
        print("no dream runs executed")
    return 0


def cmd_dream_inspect(args: argparse.Namespace, _feature_context: FeatureContext) -> int:
    diff_path = Path(args.diff_file)
    raw = json.loads(diff_path.read_text(encoding="utf-8"))
    diff = DreamDiff.from_dict(raw)

    merged_ids = [
        c.memory_id for c in diff.memory_changes if c.before is not None and c.after is not None
    ]
    archived_ids = [
        c.memory_id for c in diff.memory_changes if c.after is not None and c.after.decay.archived
    ]
    trust_adjusted_ids = [
        c.memory_id
        for c in diff.memory_changes
        if c.before is not None
        and c.after is not None
        and c.before.trust_score != c.after.trust_score
    ]
    edge_added_ids = [c.edge_id for c in diff.edge_changes if c.before is None]
    edge_removed_ids = [
        c.edge_id
        for c in diff.edge_changes
        if c.after is not None and c.after.metadata.get("archived")
    ]

    print(f"run_id={diff.run_id}")
    print(f"strategy={diff.strategy_name}")
    print(f"created_at={diff.created_at.isoformat()}")
    print(f"memory_changes={len(diff.memory_changes)}")
    print(f"edge_changes={len(diff.edge_changes)}")
    print(f"merged_count={len(merged_ids)} ids={','.join(merged_ids) or 'none'}")
    print(f"archived_count={len(archived_ids)} ids={','.join(archived_ids) or 'none'}")
    print(
        f"trust_adjusted_count={len(trust_adjusted_ids)} "
        f"ids={','.join(trust_adjusted_ids) or 'none'}"
    )
    print(f"edges_added={len(edge_added_ids)} ids={','.join(edge_added_ids) or 'none'}")
    print(f"edges_removed={len(edge_removed_ids)} ids={','.join(edge_removed_ids) or 'none'}")
    return 0


def cmd_dream_rollback(args: argparse.Namespace, _feature_context: FeatureContext) -> int:
    diff_path = Path(args.diff_file)
    raw = json.loads(diff_path.read_text(encoding="utf-8"))
    diff = DreamDiff.from_dict(raw)

    config_path = Path(args.config)
    workspace = load_workspace(config_path)
    bundle = build_storage_bundle(workspace.storage, workspace_root=config_path.parent)
    runner = DreamRunner(
        graph_store=bundle.graph_store,
        memory_store=bundle.memory_store,
    )
    runner.rollback(diff)
    print(
        f"rolled back run_id={diff.run_id} strategy={diff.strategy_name} "
        f"memory_changes={len(diff.memory_changes)} edge_changes={len(diff.edge_changes)}"
    )
    return 0


def cmd_plugin_list(_: argparse.Namespace, _feature_context: FeatureContext) -> int:
    registry = PluginRegistry()
    registry.register(InMemoryTraceSinkPlugin())
    try:
        registry.load_entry_points()
    except ValueError:
        pass
    for manifest in registry.manifests():
        capabilities = ",".join(capability.value for capability in manifest.capabilities)
        print(
            f"plugin_id={manifest.plugin_id} "
            f"capabilities={capabilities} "
            f"description={manifest.description or ''}"
        )
    registry.shutdown()
    return 0


def _selected_storage_roles(raw_roles: Sequence[str] | None) -> tuple[StorageRole, ...] | None:
    if not raw_roles:
        return None
    return tuple(cast(StorageRole, role) for role in raw_roles)


def cmd_storage_list(args: argparse.Namespace, _feature_context: FeatureContext) -> int:
    try:
        load_storage_backends_from_entry_points()
    except (TypeError, ValueError):
        pass

    providers = list_storage_backends(cast(StorageRole, args.role) if args.role else None)
    for provider in providers:
        print(f"role={provider.role} backend={provider.backend}")
    return 0


def cmd_storage_init(args: argparse.Namespace, _feature_context: FeatureContext) -> int:
    config_path = Path(args.config)
    workspace = load_workspace(config_path)
    selected_roles = _selected_storage_roles(args.role)
    resolved = setup_storage_backends(
        workspace.storage,
        workspace_root=config_path.parent,
        include_roles=selected_roles,
        backend_filter=args.backend,
        dry_run=bool(args.dry_run),
    )
    action = "planned" if args.dry_run else "initialized"
    if not resolved:
        print("no storage backends selected")
    else:
        for role, backend in resolved:
            print(f"action={action} role={role} backend={backend}")

    _record(
        config_path,
        "cli.storage.init",
        {
            "action_count": len(resolved),
            "action": action,
            "backend_filter": args.backend or "",
            "roles": list(selected_roles)
            if selected_roles is not None
            else list(STORAGE_ROLE_CHOICES),
        },
    )
    return 0


def _resolve_eval_storage_config(backend: str | None) -> StorageConfig | None:
    if backend is None or backend == "sqlite":
        return None
    if backend == "in_memory":
        return StorageConfig.with_in_memory_preset()
    return None


def cmd_eval_run(args: argparse.Namespace, _feature_context: FeatureContext) -> int:
    output_path = Path(args.output) if args.output else Path("eval-results") / f"{args.suite}.json"
    storage_config = _resolve_eval_storage_config(getattr(args, "backend", None))
    report = run_evaluation_suite(
        args.suite, output_path=output_path, storage_config=storage_config
    )
    if args.config is not None:
        _record(
            Path(args.config),
            "cli.eval",
            {
                "suite": report.suite,
                "status": report.status,
                "case_count": len(report.cases),
            },
        )
    print(f"suite={report.suite} status={report.status} output={output_path}")
    for case in report.cases:
        print(f"case_id={case.case_id} status={case.status} metrics={case.metrics}")
    return 0 if report.status == "ok" else 1


def cmd_trace_inspect(args: argparse.Namespace, _feature_context: FeatureContext) -> int:
    events = read_traces(load_workspace(Path(args.config)), limit=args.limit)
    if not events:
        print("no trace events recorded")
    else:
        for event in events:
            print(
                f"timestamp={event.timestamp.isoformat()} "
                f"name={event.name} "
                f"payload={json.dumps(event.payload, sort_keys=True)}"
            )
    return TRACE_INSPECT_SUCCESS_EXIT_CODE


def cmd_features_list(args: argparse.Namespace, feature_context: FeatureContext) -> int:
    rows = _feature_manifest_defaults(feature_context.channel)
    if args.format == "json":
        print(json.dumps(rows, indent=2, sort_keys=True))
        return 0

    code_width = max((len(str(row["code"])) for row in rows), default=4)
    name_width = max((len(str(row["name"])) for row in rows), default=4)
    lifecycle_width = max((len(str(row["lifecycle"])) for row in rows), default=9)
    default_width = max(
        (len("enabled") if row["default_enabled"] else len("disabled") for row in rows),
        default=7,
    )
    code_width = max(code_width, len("CODE"))
    name_width = max(name_width, len("NAME"))
    lifecycle_width = max(lifecycle_width, len("LIFECYCLE"))
    default_width = max(default_width, len("DEFAULT"))

    print(
        f"{'CODE':<{code_width}} "
        f"{'NAME':<{name_width}} "
        f"{'LIFECYCLE':<{lifecycle_width}} "
        f"{'DEFAULT':<{default_width}}"
    )
    for row in rows:
        default_value = "enabled" if row["default_enabled"] else "disabled"
        print(
            f"{row['code']:<{code_width}} "
            f"{row['name']:<{name_width}} "
            f"{row['lifecycle']:<{lifecycle_width}} "
            f"{default_value:<{default_width}}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cellin local-first CLI")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--enable-feature", action="append", default=[], metavar="NAME")
    parser.add_argument("--disable-feature", action="append", default=[], metavar="NAME")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("--workspace", required=True)
    init_parser.set_defaults(handler=cmd_init)

    ingest_parser = subparsers.add_parser("ingest")
    ingest_parser.add_argument("--config", required=True)
    ingest_parser.add_argument("--input", required=True)
    ingest_parser.set_defaults(handler=cmd_ingest)

    retrieve_parser = subparsers.add_parser("retrieve")
    retrieve_parser.add_argument("--config", required=True)
    retrieve_parser.add_argument("--query", required=True)
    retrieve_parser.add_argument("--top-k", type=int, default=3)
    retrieve_parser.set_defaults(handler=cmd_retrieve)

    dream_parser = subparsers.add_parser("dream")
    dream_subparsers = dream_parser.add_subparsers(dest="dream_command", required=True)

    dream_run_parser = dream_subparsers.add_parser("run")
    dream_run_parser.add_argument("--config", required=True)
    dream_run_parser.add_argument(
        "--strategy",
        choices=("deduplication", "contradiction_repair", "abstraction"),
    )
    dream_run_parser.add_argument("--diff-out", metavar="PATH")
    dream_run_parser.set_defaults(handler=cmd_dream_run)

    dream_inspect_parser = dream_subparsers.add_parser("inspect")
    dream_inspect_parser.add_argument("diff_file", metavar="diff-file")
    dream_inspect_parser.set_defaults(handler=cmd_dream_inspect)

    dream_rollback_parser = dream_subparsers.add_parser("rollback")
    dream_rollback_parser.add_argument("--config", required=True)
    dream_rollback_parser.add_argument("--diff-file", required=True, metavar="PATH")
    dream_rollback_parser.set_defaults(handler=cmd_dream_rollback)

    storage_parser = subparsers.add_parser("storage")
    storage_subparsers = storage_parser.add_subparsers(dest="storage_command", required=True)
    storage_list_parser = storage_subparsers.add_parser("list")
    storage_list_parser.add_argument("--role", choices=STORAGE_ROLE_CHOICES)
    storage_list_parser.set_defaults(handler=cmd_storage_list)
    storage_init_parser = storage_subparsers.add_parser("init")
    storage_init_parser.add_argument("--config", required=True)
    storage_init_parser.add_argument("--role", action="append", choices=STORAGE_ROLE_CHOICES)
    storage_init_parser.add_argument("--backend")
    storage_init_parser.add_argument("--dry-run", action="store_true")
    storage_init_parser.set_defaults(handler=cmd_storage_init)

    plugin_parser = subparsers.add_parser("plugin")
    plugin_subparsers = plugin_parser.add_subparsers(dest="plugin_command", required=True)
    plugin_list_parser = plugin_subparsers.add_parser("list")
    plugin_list_parser.set_defaults(handler=cmd_plugin_list)

    features_parser = subparsers.add_parser("features")
    features_subparsers = features_parser.add_subparsers(dest="features_command", required=True)
    features_list_parser = features_subparsers.add_parser("list")
    features_list_parser.add_argument(
        "--format",
        choices=("json", "table"),
        default=DEFAULT_FEATURE_LIST_FORMAT,
    )
    features_list_parser.set_defaults(handler=cmd_features_list)

    eval_parser = subparsers.add_parser("eval")
    eval_subparsers = eval_parser.add_subparsers(dest="eval_command", required=True)
    eval_run_parser = eval_subparsers.add_parser("run")
    eval_run_parser.add_argument("--suite", choices=("smoke", "full"), default="smoke")
    eval_run_parser.add_argument("--output")
    eval_run_parser.add_argument("--config")
    eval_run_parser.add_argument("--backend", choices=("sqlite", "in_memory"), default="sqlite")
    eval_run_parser.set_defaults(handler=cmd_eval_run)

    trace_parser = subparsers.add_parser("trace")
    trace_subparsers = trace_parser.add_subparsers(dest="trace_command", required=True)
    trace_inspect_parser = trace_subparsers.add_parser("inspect")
    trace_inspect_parser.add_argument("--config", required=True)
    trace_inspect_parser.add_argument("--limit", type=int, default=10)
    trace_inspect_parser.set_defaults(handler=cmd_trace_inspect)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = args.handler
    feature_context = _resolve_feature_context(args)
    return int(handler(args, feature_context))
