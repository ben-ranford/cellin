"""Structured MCP tool operations over Cellin runtime primitives."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from cellin.core import MemoryAtom, MemoryEdge, Modality
from cellin.core.models import JSONValue
from cellin.dreaming import DreamRunner
from cellin.dreaming.models import DreamMemoryChange, DreamRunResult
from cellin.ingest import ArtifactEnvelope, CanonicalIngestor
from cellin.mcp.subjects import SubjectRegistry, validate_subject_id
from cellin.ranking import WeightedRanker, get_weight_profile
from cellin.retrieval import RetrievalCandidateGenerator, WeightedRetriever
from cellin.runtime import StorageBundle

DEFAULT_RETRIEVAL_LIMIT = 5


def _metadata_topic(memory: MemoryAtom) -> str | None:
    topic = memory.metadata.get("topic")
    return topic if isinstance(topic, str) else None


def _memory_payload(memory: MemoryAtom, *, score: float | None = None) -> dict[str, JSONValue]:
    payload: dict[str, JSONValue] = {
        "memory_id": memory.memory_id,
        "text": memory.text,
        "kind": memory.kind.value,
        "modality": memory.modality.value,
        "topic": _metadata_topic(memory),
        "created_at": memory.created_at.isoformat(),
        "observed_at": memory.observed_at.isoformat() if memory.observed_at else None,
        "archived": memory.decay.archived,
        "trust_score": memory.trust_score,
        "salience_score": memory.salience_score,
        "metadata": memory.metadata,
    }
    if score is not None:
        payload["score"] = score
    return payload


def _edge_payload(edge: MemoryEdge) -> dict[str, JSONValue]:
    return {
        "edge_id": edge.edge_id,
        "kind": edge.kind.value,
        "source_id": edge.source_id,
        "target_id": edge.target_id,
        "weight": edge.weight,
        "created_at": edge.created_at.isoformat(),
        "metadata": edge.metadata,
    }


def _payload_list(values: list[dict[str, JSONValue]]) -> JSONValue:
    return cast(JSONValue, values)


def _change_type(change: DreamMemoryChange) -> str:
    if change.before is None and change.after is not None:
        return "created"
    if change.before is not None and change.after is None:
        return "deleted"
    if (
        change.before is not None
        and change.after is not None
        and not change.before.decay.archived
        and change.after.decay.archived
    ):
        return "archived"
    return "updated"


def _memory_change_payload(change: DreamMemoryChange) -> dict[str, JSONValue]:
    return {
        "memory_id": change.memory_id,
        "type": _change_type(change),
        "before_trust": change.before.trust_score if change.before is not None else None,
        "after_trust": change.after.trust_score if change.after is not None else None,
    }


def _dream_result_payload(result: DreamRunResult) -> dict[str, JSONValue]:
    changes = [_memory_change_payload(change) for change in result.diff.memory_changes]
    return {
        "strategy": result.artifact.strategy_name,
        "affected_count": len(result.artifact.affected_memory_ids),
        "affected_memory_ids": list(result.artifact.affected_memory_ids),
        "changes": _payload_list(changes),
        "edge_change_count": len(result.diff.edge_changes),
        "summary": result.artifact.summary,
    }


def _json_object(value: Mapping[str, JSONValue] | None) -> dict[str, JSONValue]:
    return dict(value or {})


def _coerce_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_RETRIEVAL_LIMIT
    return max(0, limit)


def _bundle_ingestor(bundle: StorageBundle) -> CanonicalIngestor:
    return CanonicalIngestor.with_built_in_adapters(
        graph_store=bundle.graph_store,
        memory_store=bundle.memory_store,
        vector_store=bundle.vector_store,
        representation_store=bundle.representation_store,
    )


def _bundle_retriever(bundle: StorageBundle) -> WeightedRetriever:
    profile = get_weight_profile("balanced")
    return WeightedRetriever(
        candidate_generator=RetrievalCandidateGenerator(
            memory_store=bundle.memory_store,
            graph_store=bundle.graph_store,
            vector_store=bundle.vector_store,
        ),
        ranker=WeightedRanker(profile=profile),
        profile=profile,
        memory_store=bundle.memory_store,
        representation_store=bundle.representation_store,
    )


def _bundle_dream_runner(bundle: StorageBundle) -> DreamRunner:
    return DreamRunner(
        graph_store=bundle.graph_store,
        memory_store=bundle.memory_store,
        vector_store=bundle.vector_store,
    )


@dataclass(slots=True)
class CellinMCPTools:
    """Runtime-backed implementation of Cellin's MCP tool surface."""

    subject_registry: SubjectRegistry
    now_provider: Callable[[], datetime] = lambda: datetime.now(UTC)

    def ingest_memory(
        self,
        subject: str,
        text: str,
        topic: str | None = None,
        modality: str = "text",
        metadata: Mapping[str, JSONValue] | None = None,
    ) -> dict[str, JSONValue]:
        """Ingest one memory atom into a subject-scoped store."""

        normalized_subject = validate_subject_id(subject)
        if not text.strip():
            raise ValueError("`text` must be a non-empty string.")

        payload_metadata = _json_object(metadata)
        if topic is not None:
            payload_metadata["topic"] = topic

        bundle = self.subject_registry.get_or_create(normalized_subject)
        envelope_id = f"mcp-{uuid4().hex}"
        result = _bundle_ingestor(bundle).ingest_envelopes(
            (
                ArtifactEnvelope(
                    envelope_id=envelope_id,
                    modality=Modality(modality),
                    payload=text,
                    source_id=envelope_id,
                    source_type="mcp",
                    observed_at=self.now_provider(),
                    metadata=payload_metadata,
                ),
            )
        )

        return {
            "subject": normalized_subject,
            "memory": _memory_payload(result.memories[0]),
            "edges": _payload_list([_edge_payload(edge) for edge in result.edges]),
        }

    def retrieve_memories(
        self,
        subject: str,
        query: str,
        limit: int | None = None,
    ) -> dict[str, JSONValue]:
        """Retrieve scored memories for a subject."""

        normalized_subject = validate_subject_id(subject)
        bundle = self.subject_registry.get_or_create(normalized_subject)
        result = _bundle_retriever(bundle).retrieve(query, top_k=_coerce_limit(limit))
        return {
            "subject": normalized_subject,
            "query": result.query,
            "total_score": result.total_score,
            "memories": _payload_list(
                [_memory_payload(scored.memory, score=scored.score) for scored in result.memories]
            ),
        }

    def run_dream(
        self,
        subject: str,
        strategy: str | None = None,
    ) -> dict[str, JSONValue]:
        """Run one dream strategy, or all currently pending dream runs."""

        normalized_subject = validate_subject_id(subject)
        bundle = self.subject_registry.get_or_create(normalized_subject)
        runner = _bundle_dream_runner(bundle)
        if strategy is None:
            results = runner.run_pending()
            strategy_name = "pending"
        else:
            result = runner.run_strategy(strategy)
            results = () if result is None else (result,)
            strategy_name = strategy

        run_payloads = [_dream_result_payload(result) for result in results]
        changes = [
            change
            for result in run_payloads
            for change in cast(list[dict[str, JSONValue]], result["changes"])
        ]
        return {
            "subject": normalized_subject,
            "strategy": strategy_name,
            "affected_count": sum(cast(int, result["affected_count"]) for result in run_payloads),
            "changes": _payload_list(changes),
            "runs": _payload_list(run_payloads),
        }

    def inspect_graph(
        self,
        subject: str,
        memory_id: str | None = None,
    ) -> dict[str, JSONValue]:
        """Inspect either a subject's full graph or one memory's neighbors."""

        normalized_subject = validate_subject_id(subject)
        bundle = self.subject_registry.get_or_create(normalized_subject)
        if memory_id is not None:
            memory = bundle.memory_store.get(memory_id) or bundle.graph_store.get_memory(memory_id)
            return {
                "subject": normalized_subject,
                "memory": _memory_payload(memory) if memory is not None else None,
                "edges": _payload_list(
                    [_edge_payload(edge) for edge in bundle.graph_store.neighbors(memory_id)]
                ),
            }

        return {
            "subject": normalized_subject,
            "memories": _payload_list(
                [_memory_payload(memory) for memory in bundle.memory_store.list()]
            ),
            "edges": _payload_list(
                [_edge_payload(edge) for edge in bundle.graph_store.list_edges()]
            ),
        }

    def list_memories(
        self,
        subject: str,
        topic: str | None = None,
        archived: bool | None = None,
    ) -> dict[str, JSONValue]:
        """List subject memories with optional topic and archived filters."""

        normalized_subject = validate_subject_id(subject)
        bundle = self.subject_registry.get_or_create(normalized_subject)
        memories = bundle.memory_store.list_by(topic=topic, archived=archived)
        return {
            "subject": normalized_subject,
            "memories": _payload_list([_memory_payload(memory) for memory in memories]),
        }


def dispatch_tool(
    tools: CellinMCPTools,
    name: str,
    arguments: Mapping[str, Any] | None,
) -> dict[str, JSONValue]:
    """Dispatch an MCP tool call by name."""

    args = dict(arguments or {})
    if name == "ingest_memory":
        return tools.ingest_memory(
            subject=str(args["subject"]),
            text=str(args["text"]),
            topic=str(args["topic"]) if args.get("topic") is not None else None,
            modality=str(args.get("modality", "text")),
            metadata=cast(Mapping[str, JSONValue] | None, args.get("metadata")),
        )
    if name == "retrieve_memories":
        return tools.retrieve_memories(
            subject=str(args["subject"]),
            query=str(args["query"]),
            limit=cast(int | None, args.get("limit")),
        )
    if name == "run_dream":
        return tools.run_dream(
            subject=str(args["subject"]),
            strategy=str(args["strategy"]) if args.get("strategy") is not None else None,
        )
    if name == "inspect_graph":
        return tools.inspect_graph(
            subject=str(args["subject"]),
            memory_id=str(args["memory_id"]) if args.get("memory_id") is not None else None,
        )
    if name == "list_memories":
        return tools.list_memories(
            subject=str(args["subject"]),
            topic=str(args["topic"]) if args.get("topic") is not None else None,
            archived=cast(bool | None, args.get("archived")),
        )
    raise ValueError(f"Unknown MCP tool `{name}`.")
