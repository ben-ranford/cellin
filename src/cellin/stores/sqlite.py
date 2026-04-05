"""SQLite-backed memory and graph persistence."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from cellin.core import (
    DecayState,
    EdgeKind,
    EmbeddingRecord,
    MemoryAtom,
    MemoryEdge,
    MemoryKind,
    MemoryStore,
    Modality,
    Provenance,
    RetrievalStats,
)


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


def _dump_memory(memory: MemoryAtom) -> str:
    payload = {
        "memory_id": memory.memory_id,
        "kind": memory.kind.value,
        "text": memory.text,
        "provenance": {
            "source_id": memory.provenance.source_id,
            "source_type": memory.provenance.source_type,
            "uri": memory.provenance.uri,
            "ingest_run_id": memory.provenance.ingest_run_id,
            "metadata": memory.provenance.metadata,
        },
        "modality": memory.modality.value,
        "created_at": _dt(memory.created_at),
        "observed_at": _dt(memory.observed_at),
        "artifact_id": memory.artifact_id,
        "salience_score": memory.salience_score,
        "trust_score": memory.trust_score,
        "decay": {
            "archived": memory.decay.archived,
            "half_life_days": memory.decay.half_life_days,
            "last_reinforced_at": _dt(memory.decay.last_reinforced_at),
        },
        "retrieval": {
            "access_count": memory.retrieval.access_count,
            "last_accessed_at": _dt(memory.retrieval.last_accessed_at),
        },
        "embeddings": [
            {"key": embedding.key, "vector": embedding.vector, "model": embedding.model}
            for embedding in memory.embeddings
        ],
        "metadata": memory.metadata,
    }
    return json.dumps(payload, sort_keys=True)


def _load_memory(payload: str) -> MemoryAtom:
    raw = json.loads(payload)
    return MemoryAtom(
        memory_id=raw["memory_id"],
        kind=MemoryKind(raw["kind"]),
        text=raw["text"],
        provenance=Provenance(**raw["provenance"]),
        modality=Modality(raw["modality"]),
        created_at=datetime.fromisoformat(raw["created_at"]),
        observed_at=_parse_dt(raw["observed_at"]),
        artifact_id=raw["artifact_id"],
        salience_score=raw["salience_score"],
        trust_score=raw["trust_score"],
        decay=DecayState(
            archived=raw["decay"]["archived"],
            half_life_days=raw["decay"]["half_life_days"],
            last_reinforced_at=_parse_dt(raw["decay"]["last_reinforced_at"]),
        ),
        retrieval=RetrievalStats(
            access_count=raw["retrieval"]["access_count"],
            last_accessed_at=_parse_dt(raw["retrieval"]["last_accessed_at"]),
        ),
        embeddings=tuple(
            EmbeddingRecord(
                key=entry["key"],
                vector=tuple(float(value) for value in entry["vector"]),
                model=entry["model"],
            )
            for entry in raw["embeddings"]
        ),
        metadata=raw["metadata"],
    )


def _dump_edge(edge: MemoryEdge) -> str:
    payload = {
        "edge_id": edge.edge_id,
        "source_id": edge.source_id,
        "target_id": edge.target_id,
        "kind": edge.kind.value,
        "provenance": {
            "source_id": edge.provenance.source_id,
            "source_type": edge.provenance.source_type,
            "uri": edge.provenance.uri,
            "ingest_run_id": edge.provenance.ingest_run_id,
            "metadata": edge.provenance.metadata,
        },
        "created_at": _dt(edge.created_at),
        "weight": edge.weight,
        "metadata": edge.metadata,
    }
    return json.dumps(payload, sort_keys=True)


def _load_edge(payload: str) -> MemoryEdge:
    raw = json.loads(payload)
    return MemoryEdge(
        edge_id=raw["edge_id"],
        source_id=raw["source_id"],
        target_id=raw["target_id"],
        kind=EdgeKind(raw["kind"]),
        provenance=Provenance(**raw["provenance"]),
        created_at=datetime.fromisoformat(raw["created_at"]),
        weight=raw["weight"],
        metadata=raw["metadata"],
    )


def _edge_archived(edge: MemoryEdge) -> bool:
    archived = edge.metadata.get("archived")
    return bool(archived) if isinstance(archived, bool) else False


class _SQLiteBackend:
    """Shared SQLite boundary for memory and graph persistence."""

    def __init__(self, database_path: str) -> None:
        self.database_path = database_path
        self._ensure_parent_directory()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path)

    def _ensure_parent_directory(self) -> None:
        if self.database_path == ":memory:":
            return
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS edges (
                    edge_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )

    def put_memories(self, memories: tuple[MemoryAtom, ...]) -> None:
        if not memories:
            return
        rows = [(memory.memory_id, _dump_memory(memory)) for memory in memories]
        with closing(self._connect()) as connection, connection:
            connection.executemany(
                """
                INSERT INTO memories(memory_id, payload)
                VALUES (?, ?)
                ON CONFLICT(memory_id) DO UPDATE SET payload = excluded.payload
                """,
                rows,
            )

    def get_memory(self, memory_id: str) -> MemoryAtom | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT payload FROM memories WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
        if row is None:
            return None
        return _load_memory(row[0])

    def list_memories(self) -> tuple[MemoryAtom, ...]:
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT payload FROM memories ORDER BY memory_id").fetchall()
        return tuple(_load_memory(row[0]) for row in rows)

    def upsert_edges(self, edges: tuple[MemoryEdge, ...]) -> None:
        if not edges:
            return
        rows = [(edge.edge_id, edge.source_id, edge.target_id, _dump_edge(edge)) for edge in edges]
        with closing(self._connect()) as connection, connection:
            connection.executemany(
                """
                INSERT INTO edges(edge_id, source_id, target_id, payload)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(edge_id) DO UPDATE SET payload = excluded.payload
                """,
                rows,
            )

    def neighbors(self, memory_id: str) -> tuple[MemoryEdge, ...]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT payload
                FROM edges
                WHERE source_id = ? OR target_id = ?
                ORDER BY edge_id
                """,
                (memory_id, memory_id),
            ).fetchall()
        return tuple(edge for row in rows if not _edge_archived(edge := _load_edge(row[0])))

    def list_edges(self) -> tuple[MemoryEdge, ...]:
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT payload FROM edges ORDER BY edge_id").fetchall()
        return tuple(edge for row in rows if not _edge_archived(edge := _load_edge(row[0])))


_BACKENDS: dict[str, _SQLiteBackend] = {}


def _backend_for(database_path: str) -> _SQLiteBackend:
    resolved_path = str(Path(database_path).resolve())
    backend = _BACKENDS.get(resolved_path)
    if backend is None:
        backend = _SQLiteBackend(resolved_path)
        _BACKENDS[resolved_path] = backend
    return backend


class _SQLiteBase:
    def __init__(self, database_path: str, *, backend: _SQLiteBackend | None = None) -> None:
        self._backend = backend or _backend_for(database_path)
        self._database_path = self._backend.database_path


class SQLiteMemoryStore(_SQLiteBase):
    """Persists memory atoms in SQLite as JSON payloads."""

    def put(self, memory: MemoryAtom) -> None:
        self.put_many((memory,))

    def put_many(self, memories: tuple[MemoryAtom, ...]) -> None:
        self._backend.put_memories(memories)

    def get(self, memory_id: str) -> MemoryAtom | None:
        return self._backend.get_memory(memory_id)

    def list(self) -> tuple[MemoryAtom, ...]:
        return self._backend.list_memories()


class SQLiteGraphStore(_SQLiteBase):
    """Persists graph edges and reads graph-backed memory state from SQLite."""

    def upsert_memory(self, memory: MemoryAtom) -> None:
        self._backend.put_memories((memory,))

    def upsert_memories(self, memories: tuple[MemoryAtom, ...]) -> None:
        self._backend.put_memories(memories)

    def upsert_edge(self, edge: MemoryEdge) -> None:
        self.upsert_edges((edge,))

    def upsert_edges(self, edges: tuple[MemoryEdge, ...]) -> None:
        self._backend.upsert_edges(edges)

    def shares_memory_store(self, memory_store: MemoryStore) -> bool:
        return (
            isinstance(memory_store, SQLiteMemoryStore) and memory_store._backend is self._backend
        )

    def get_memory(self, memory_id: str) -> MemoryAtom | None:
        return self._backend.get_memory(memory_id)

    def neighbors(self, memory_id: str) -> tuple[MemoryEdge, ...]:
        return self._backend.neighbors(memory_id)

    def list_edges(self) -> tuple[MemoryEdge, ...]:
        return self._backend.list_edges()
