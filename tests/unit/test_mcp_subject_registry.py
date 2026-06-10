"""Unit tests for MCP subject routing."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from cellin.core import Artifact, Modality, Provenance
from cellin.ingest.pipeline import CanonicalIngestor
from cellin.mcp import SubjectRegistry
from cellin.runtime.storage import StorageBackendConfig, StorageConfig

_NOW = datetime(2026, 6, 11, tzinfo=UTC)


def _artifact(artifact_id: str, text: str, *, topic: str) -> Artifact:
    return Artifact(
        artifact_id=artifact_id,
        modality=Modality.TEXT,
        content=text,
        provenance=Provenance(source_id=artifact_id, source_type="fixture"),
        created_at=_NOW,
        metadata={"topic": topic},
    )


def _ingest_topic(
    registry: SubjectRegistry,
    subject_id: str,
    *,
    artifact_id: str,
    topic: str,
) -> None:
    bundle = registry.get_or_create(subject_id)
    ingestor = CanonicalIngestor.with_built_in_adapters(
        graph_store=bundle.graph_store,
        memory_store=bundle.memory_store,
        vector_store=bundle.vector_store,
        representation_store=bundle.representation_store,
    )
    ingestor.ingest((_artifact(artifact_id, f"{topic} notes for {subject_id}", topic=topic),))


def test_get_or_create_reuses_existing_bundle(tmp_path: Path) -> None:
    registry = SubjectRegistry(workspace_root=tmp_path)

    first = registry.get_or_create("alpha")
    second = registry.get_or_create("alpha")

    assert first is second


@pytest.mark.parametrize("subject_id", ["", "Alpha", "alpha beta", "../alpha", "alpha!"])
def test_invalid_subject_ids_raise_descriptive_error(tmp_path: Path, subject_id: str) -> None:
    registry = SubjectRegistry(workspace_root=tmp_path)

    with pytest.raises(ValueError, match=r"\[a-z0-9_-\]\+"):
        registry.get_or_create(subject_id)


def test_storage_config_for_sqlite_is_subject_scoped_and_deterministic(tmp_path: Path) -> None:
    registry = SubjectRegistry(workspace_root=tmp_path, data_directory="subject-data")

    alpha = registry.storage_config_for("alpha")
    alpha_again = registry.storage_config_for("alpha")
    beta = registry.storage_config_for("beta")

    assert alpha == alpha_again
    assert alpha.memory.database_path == str(
        (tmp_path / "subject-data" / "cellin_alpha.db").resolve()
    )
    assert alpha.graph.database_path == alpha.memory.database_path
    assert alpha.vector.backend == "in_memory_vector_index"
    assert beta.memory.database_path == str(
        (tmp_path / "subject-data" / "cellin_beta.db").resolve()
    )


def test_storage_config_for_remote_backends_adds_subject_namespace_when_supported(
    tmp_path: Path,
) -> None:
    registry = SubjectRegistry(
        workspace_root=tmp_path,
        storage_config=StorageConfig(
            memory=StorageBackendConfig("mongodb", "mongodb://localhost:27017/cellin"),
            graph=StorageBackendConfig("mongodb", "mongodb://localhost:27017/cellin"),
            vector=StorageBackendConfig("pinecone", "https://example.pinecone.io/main"),
            representation=StorageBackendConfig("qdrant", "http://localhost:6333?collection=main"),
        ),
    )

    config = registry.storage_config_for("atlas")

    assert config.memory.database_path == "mongodb://localhost:27017/cellin_atlas"
    assert config.graph.database_path == "mongodb://localhost:27017/cellin_atlas"
    assert config.vector.database_path == "https://example.pinecone.io/main?namespace=atlas"
    assert config.representation.database_path == "http://localhost:6333?collection=cellin_atlas"


def test_storage_config_for_duckdb_and_unscoped_backends(tmp_path: Path) -> None:
    registry = SubjectRegistry(
        workspace_root=tmp_path,
        storage_config=StorageConfig(
            memory=StorageBackendConfig("duckdb", "main.duckdb"),
            graph=StorageBackendConfig("mongodb"),
            vector=StorageBackendConfig("custom_vector", "custom://shared"),
            representation=StorageBackendConfig("weaviate", "http://localhost:8080"),
        ),
    )

    config = registry.storage_config_for("atlas")

    assert config.memory.database_path == str((tmp_path / "data" / "cellin_atlas.duckdb").resolve())
    assert config.graph == StorageBackendConfig("mongodb")
    assert config.vector == StorageBackendConfig("custom_vector", "custom://shared")
    assert config.representation.database_path == "http://localhost:8080?collection=cellin_atlas"


def test_list_subjects_reports_isolated_counts_for_same_topic(tmp_path: Path) -> None:
    registry = SubjectRegistry(workspace_root=tmp_path)
    _ingest_topic(registry, "subject-a", artifact_id="a-1", topic="release-plan")

    registry.get_or_create("subject-b")
    summaries = {summary.subject_id: summary for summary in registry.list_subjects()}

    assert summaries["subject-a"].memory_count == 1
    assert summaries["subject-a"].edge_count == 0
    assert summaries["subject-b"].memory_count == 0
    assert summaries["subject-b"].edge_count == 0


def test_subject_state_persists_across_registry_restart(tmp_path: Path) -> None:
    first_registry = SubjectRegistry(workspace_root=tmp_path)
    _ingest_topic(first_registry, "subject-a", artifact_id="a-1", topic="design-review")

    second_registry = SubjectRegistry(workspace_root=tmp_path)
    summary = second_registry.list_subjects()
    bundle = second_registry.get_or_create("subject-a")

    assert [item.subject_id for item in summary] == ["subject-a"]
    assert len(bundle.memory_store.list()) == 1


def test_delete_subject_requires_confirmation_and_removes_local_storage(tmp_path: Path) -> None:
    registry = SubjectRegistry(workspace_root=tmp_path)
    _ingest_topic(registry, "subject-a", artifact_id="a-1", topic="cleanup")
    database_path = Path(registry.storage_config_for("subject-a").memory.database_path or "")

    with pytest.raises(ValueError, match="confirm=True"):
        registry.delete_subject("subject-a")

    assert database_path.exists()
    assert registry.delete_subject("subject-a", confirm=True) is True
    assert not database_path.exists()
    assert registry.list_subjects() == ()


def test_subject_index_rejects_non_list_payload(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "subjects.json").write_text('{"subject": "alpha"}', encoding="utf-8")

    with pytest.raises(ValueError, match="JSON array"):
        SubjectRegistry(workspace_root=tmp_path)


def test_delete_unknown_subject_returns_false_and_clears_cached_bundle(tmp_path: Path) -> None:
    registry = SubjectRegistry(workspace_root=tmp_path)
    cached_bundle = registry.get_or_create("orphan")
    registry._known_subject_ids.remove("orphan")
    registry._persist_known_subject_ids()

    assert registry.delete_subject("orphan", confirm=True) is False
    assert registry._bundles.get("orphan") is None
    assert cached_bundle is not registry.get_or_create("orphan")


def test_delete_subject_rejects_remote_backend_mix_without_local_paths(tmp_path: Path) -> None:
    registry = SubjectRegistry(
        workspace_root=tmp_path,
        storage_config=StorageConfig(
            memory=StorageBackendConfig("mongodb", "mongodb://localhost:27017/cellin"),
            graph=StorageBackendConfig("mongodb", "mongodb://localhost:27017/cellin"),
            vector=StorageBackendConfig("pinecone", "https://example.pinecone.io/main"),
            representation=StorageBackendConfig("qdrant", "http://localhost:6333?collection=main"),
        ),
    )
    registry._known_subject_ids.add("remote")
    registry._persist_known_subject_ids()

    with pytest.raises(NotImplementedError, match="remote backend mix"):
        registry.delete_subject("remote", confirm=True)


def test_delete_ephemeral_subject_reports_removed_without_files(tmp_path: Path) -> None:
    registry = SubjectRegistry(
        workspace_root=tmp_path,
        storage_config=StorageConfig.with_in_memory_preset(),
    )
    registry._known_subject_ids.add("scratch")
    registry._persist_known_subject_ids()

    assert registry.delete_subject("scratch", confirm=True) is True
    assert registry.list_subjects() == ()
