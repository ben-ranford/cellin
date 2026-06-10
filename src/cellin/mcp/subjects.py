"""Subject-aware storage routing for the future MCP server."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from cellin.runtime.storage import (
    StorageBackendConfig,
    StorageBundle,
    StorageConfig,
    build_storage_bundle,
)
from cellin.stores import sql_backends
from cellin.stores import sqlite as sqlite_stores

_SUBJECT_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9_-]+$", re.ASCII)
_SUBJECT_COLLECTION_PREFIX: Final[str] = "cellin_"
_SUBJECT_INDEX_FILENAME: Final[str] = "subjects.json"


@dataclass(frozen=True, slots=True)
class SubjectSummary:
    """Current storage counts for a known subject."""

    subject_id: str
    memory_count: int
    edge_count: int


def validate_subject_id(subject_id: str) -> str:
    """Validate and normalize a slug-safe subject identifier."""

    normalized = subject_id.strip()
    if not normalized:
        raise ValueError("Subject ID must be a non-empty slug-safe string matching `[a-z0-9_-]+`.")
    if _SUBJECT_ID_RE.fullmatch(normalized) is None:
        raise ValueError(
            f"Invalid subject ID `{subject_id}`. Subject IDs must match `[a-z0-9_-]+`."
        )
    return normalized


class SubjectRegistry:
    """Lazily provisions isolated storage bundles per subject ID."""

    def __init__(
        self,
        *,
        workspace_root: Path | str,
        storage_config: StorageConfig | None = None,
        data_directory: Path | str = "data",
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.data_directory = self._resolve_data_directory(data_directory)
        self._base_storage_config = storage_config or StorageConfig.with_sqlite_preset(
            "cellin.sqlite"
        )
        self._bundles: dict[str, StorageBundle] = {}
        self._known_subject_ids = self._load_known_subject_ids()

    def get_or_create(self, subject_id: str) -> StorageBundle:
        """Return an existing bundle or provision an isolated bundle for subject_id."""

        normalized = validate_subject_id(subject_id)
        bundle = self._bundles.get(normalized)
        if bundle is not None:
            return bundle

        subject_storage = self.storage_config_for(normalized)
        bundle = build_storage_bundle(subject_storage, workspace_root=self.workspace_root)
        self._bundles[normalized] = bundle
        if normalized not in self._known_subject_ids:
            self._known_subject_ids.add(normalized)
            self._persist_known_subject_ids()
        return bundle

    def storage_config_for(self, subject_id: str) -> StorageConfig:
        """Return the subject-scoped storage config derived from the base config."""

        normalized = validate_subject_id(subject_id)
        return StorageConfig(
            memory=self._route_backend(self._base_storage_config.memory, subject_id=normalized),
            graph=self._route_backend(self._base_storage_config.graph, subject_id=normalized),
            vector=self._route_backend(self._base_storage_config.vector, subject_id=normalized),
            representation=self._route_backend(
                self._base_storage_config.representation,
                subject_id=normalized,
            ),
        )

    def list_subjects(self) -> tuple[SubjectSummary, ...]:
        """Return known subject IDs with current memory and edge counts."""

        summaries: list[SubjectSummary] = []
        for subject_id in sorted(self._known_subject_ids):
            bundle = self.get_or_create(subject_id)
            summaries.append(
                SubjectSummary(
                    subject_id=subject_id,
                    memory_count=len(bundle.memory_store.list()),
                    edge_count=len(bundle.graph_store.list_edges()),
                )
            )
        return tuple(summaries)

    def delete_subject(self, subject_id: str, *, confirm: bool = False) -> bool:
        """Delete all known local storage for subject_id when confirmation is explicit."""

        normalized = validate_subject_id(subject_id)
        if not confirm:
            raise ValueError(f"Refusing to delete subject `{normalized}` without `confirm=True`.")
        if normalized not in self._known_subject_ids:
            self._bundles.pop(normalized, None)
            return False

        subject_storage = self.storage_config_for(normalized)
        local_paths = self._subject_local_paths(subject_storage)
        if not local_paths and not self._uses_only_ephemeral_backends(subject_storage):
            raise NotImplementedError(
                f"Subject deletion for `{normalized}` is not supported for the configured "
                "remote backend mix."
            )

        removed_any = False
        for path in local_paths:
            self._clear_local_backend_caches(path)
            if path.exists():
                path.unlink()
                removed_any = True

        self._bundles.pop(normalized, None)
        self._known_subject_ids.remove(normalized)
        self._persist_known_subject_ids()
        return removed_any or self._uses_only_ephemeral_backends(subject_storage)

    def _resolve_data_directory(self, data_directory: Path | str) -> Path:
        configured = Path(data_directory)
        resolved = configured if configured.is_absolute() else self.workspace_root / configured
        resolved.mkdir(parents=True, exist_ok=True)
        return resolved.resolve()

    def _load_known_subject_ids(self) -> set[str]:
        if not self._subject_index_path.exists():
            return set()

        raw = json.loads(self._subject_index_path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("Subject index must be a JSON array of subject IDs.")
        return {validate_subject_id(str(subject_id)) for subject_id in raw}

    def _persist_known_subject_ids(self) -> None:
        payload = json.dumps(sorted(self._known_subject_ids), indent=2)
        self._subject_index_path.write_text(payload + "\n", encoding="utf-8")

    @property
    def _subject_index_path(self) -> Path:
        return self.data_directory / _SUBJECT_INDEX_FILENAME

    def _route_backend(
        self,
        config: StorageBackendConfig,
        *,
        subject_id: str,
    ) -> StorageBackendConfig:
        database_path = config.database_path
        if config.backend in {"sqlite", "sqlite_vec"}:
            return StorageBackendConfig(config.backend, self._subject_sqlite_path(subject_id))
        if config.backend == "duckdb":
            return StorageBackendConfig(config.backend, self._subject_duckdb_path(subject_id))
        if database_path is None:
            return config
        if config.backend == "mongodb":
            return StorageBackendConfig(
                config.backend,
                _replace_url_path(database_path, f"/{_SUBJECT_COLLECTION_PREFIX}{subject_id}"),
            )
        if config.backend == "pinecone":
            return StorageBackendConfig(
                config.backend,
                _replace_query_value(database_path, namespace=subject_id),
            )
        if config.backend in {"milvus", "qdrant", "redis_vector", "weaviate"}:
            return StorageBackendConfig(
                config.backend,
                _replace_query_value(
                    database_path,
                    collection=f"{_SUBJECT_COLLECTION_PREFIX}{subject_id}",
                ),
            )
        return config

    def _subject_local_paths(self, storage: StorageConfig) -> tuple[Path, ...]:
        paths: set[Path] = set()
        for config in (
            storage.memory,
            storage.graph,
            storage.vector,
            storage.representation,
        ):
            database_path = config.database_path
            if database_path is None or database_path == ":memory:":
                continue
            if config.backend not in {"duckdb", "sqlite", "sqlite_vec"}:
                continue
            paths.add(self._resolve_storage_path(database_path))
        return tuple(sorted(paths))

    def _resolve_storage_path(self, database_path: str) -> Path:
        configured = Path(database_path)
        resolved = configured if configured.is_absolute() else self.workspace_root / configured
        return resolved.resolve()

    def _subject_sqlite_path(self, subject_id: str) -> str:
        return str((self.data_directory / f"{_SUBJECT_COLLECTION_PREFIX}{subject_id}.db").resolve())

    def _subject_duckdb_path(self, subject_id: str) -> str:
        return str(
            (self.data_directory / f"{_SUBJECT_COLLECTION_PREFIX}{subject_id}.duckdb").resolve()
        )

    def _uses_only_ephemeral_backends(self, storage: StorageConfig) -> bool:
        ephemeral = {"in_memory", "in_memory_vector_index"}
        return all(
            config.backend in ephemeral
            for config in (
                storage.memory,
                storage.graph,
                storage.vector,
                storage.representation,
            )
        )

    def _clear_local_backend_caches(self, path: Path) -> None:
        resolved_path = str(path.resolve())

        sqlite_stores._BACKENDS.pop(resolved_path, None)
        sql_backends._BACKENDS.pop(("duckdb", resolved_path), None)


def _replace_query_value(connection_string: str, **updates: str) -> str:
    parsed = urlparse(connection_string)
    query = parse_qs(parsed.query, keep_blank_values=True)
    for key, value in updates.items():
        query[key] = [value]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def _replace_url_path(connection_string: str, path: str) -> str:
    parsed = urlparse(connection_string)
    return urlunparse(parsed._replace(path=path))
