"""Argparse-based local CLI for Cellin."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from cellin import __version__
from cellin.cli.config import (
    ResolvedWorkspace,
    append_trace,
    init_workspace,
    load_workspace,
    read_traces,
)
from cellin.core import Modality
from cellin.core.models import JSONValue
from cellin.dreaming import DreamRunner
from cellin.evals import run_evaluation_suite
from cellin.ingest import ArtifactEnvelope, CanonicalIngestor
from cellin.ranking import WeightedRanker, get_weight_profile
from cellin.retrieval import RetrievalCandidateGenerator, WeightedRetriever
from cellin.runtime import (
    InMemoryTraceSinkPlugin,
    PluginRegistry,
    StorageBundle,
    build_storage_bundle,
)

TRACE_INSPECT_SUCCESS_EXIT_CODE = 0


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
        candidate_generator=RetrievalCandidateGenerator(bundle.memory_store, bundle.graph_store),
        ranker=WeightedRanker(profile=profile),
        profile=profile,
    )


def _record(config_path: Path, name: str, payload: dict[str, JSONValue]) -> None:
    append_trace(load_workspace(config_path), name=name, payload=payload)


def cmd_init(args: argparse.Namespace) -> int:
    config_path = init_workspace(Path(args.workspace))
    print(f"initialized workspace config={config_path}")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
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


def cmd_retrieve(args: argparse.Namespace) -> int:
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


def cmd_dream(args: argparse.Namespace) -> int:
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
    if not completed:
        print("no dream runs executed")
    return 0


def cmd_plugin_list(_: argparse.Namespace) -> int:
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


def cmd_eval_run(args: argparse.Namespace) -> int:
    output_path = Path(args.output) if args.output else Path("eval-results") / f"{args.suite}.json"
    report = run_evaluation_suite(args.suite, output_path=output_path)
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


def cmd_trace_inspect(args: argparse.Namespace) -> int:
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cellin local-first CLI")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
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
    dream_parser.add_argument("--config", required=True)
    dream_parser.add_argument(
        "--strategy",
        choices=("deduplication", "contradiction_repair", "abstraction"),
    )
    dream_parser.set_defaults(handler=cmd_dream)

    plugin_parser = subparsers.add_parser("plugin")
    plugin_subparsers = plugin_parser.add_subparsers(dest="plugin_command", required=True)
    plugin_list_parser = plugin_subparsers.add_parser("list")
    plugin_list_parser.set_defaults(handler=cmd_plugin_list)

    eval_parser = subparsers.add_parser("eval")
    eval_subparsers = eval_parser.add_subparsers(dest="eval_command", required=True)
    eval_run_parser = eval_subparsers.add_parser("run")
    eval_run_parser.add_argument("--suite", choices=("smoke", "full"), default="smoke")
    eval_run_parser.add_argument("--output")
    eval_run_parser.add_argument("--config")
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
    return int(handler(args))
