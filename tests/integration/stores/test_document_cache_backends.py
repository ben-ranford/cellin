"""Integration coverage for MongoDB and Redis-backed memory and graph stores."""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import UTC, datetime
from types import ModuleType

import pytest

from cellin.core import (
    DecayState,
    EdgeKind,
    MemoryAtom,
    MemoryEdge,
    MemoryKind,
    Modality,
    Provenance,
    RetrievalStats,
)
from cellin.stores import MongoDBGraphStore, MongoDBMemoryStore, RedisGraphStore, RedisMemoryStore
from cellin.stores import mongodb as mongodb_stores
from cellin.stores import redis as redis_stores


def _memory(memory_id: str, text: str) -> MemoryAtom:
    now = datetime(2026, 4, 5, tzinfo=UTC)
    return MemoryAtom(
        memory_id=memory_id,
        kind=MemoryKind.ATOM,
        text=text,
        provenance=Provenance(source_id=memory_id, source_type="fixture"),
        modality=Modality.TEXT,
        created_at=now,
        observed_at=now,
        decay=DecayState(half_life_days=14.0),
        retrieval=RetrievalStats(),
    )


def _edge(edge_id: str, source_id: str, target_id: str, *, archived: bool) -> MemoryEdge:
    return MemoryEdge(
        edge_id=edge_id,
        source_id=source_id,
        target_id=target_id,
        kind=EdgeKind.SUPPORTS,
        provenance=Provenance(source_id=edge_id, source_type="fixture"),
        created_at=datetime(2026, 4, 5, tzinfo=UTC),
        metadata={"archived": archived},
    )


class _FakeMongoCollection:
    def __init__(self) -> None:
        self._documents: dict[str, dict[str, object]] = {}

    def update_one(
        self,
        query: dict[str, object],
        update: dict[str, dict[str, object]],
        *,
        upsert: bool,
    ) -> None:
        del upsert
        document = dict(update["$set"])
        self._documents[str(query["_id"])] = document

    def find_one(self, query: dict[str, object]) -> dict[str, object] | None:
        document = self._documents.get(str(query["_id"]))
        return dict(document) if document is not None else None

    def find(self, query: dict[str, object] | None = None) -> list[dict[str, object]]:
        rows = list(self._documents.values())
        if query is None:
            return [dict(row) for row in rows]
        conditions = query.get("$or", [])
        assert isinstance(conditions, list)
        result = []
        for row in rows:
            for condition in conditions:
                assert isinstance(condition, dict)
                field, expected = next(iter(condition.items()))
                if row.get(field) == expected:
                    result.append(dict(row))
                    break
        return result


class _FakeMongoDatabase:
    def __init__(self) -> None:
        self._collections: dict[str, _FakeMongoCollection] = {}

    def __getitem__(self, name: str) -> _FakeMongoCollection:
        collection = self._collections.get(name)
        if collection is None:
            collection = _FakeMongoCollection()
            self._collections[name] = collection
        return collection


class _FakeMongoClient:
    def __init__(self) -> None:
        self._databases: dict[str, _FakeMongoDatabase] = {}

    def __getitem__(self, name: str) -> _FakeMongoDatabase:
        database = self._databases.get(name)
        if database is None:
            database = _FakeMongoDatabase()
            self._databases[name] = database
        return database


class _FakeRedisClient:
    def __init__(self) -> None:
        self._payloads: dict[str, str] = {}

    def set(self, key: str, value: str) -> None:
        self._payloads[key] = value

    def get(self, key: str) -> str | None:
        return self._payloads.get(key)

    def scan_iter(self, pattern: str) -> tuple[str, ...]:
        prefix = pattern[:-1] if pattern.endswith("*") else pattern
        return tuple(key for key in sorted(self._payloads) if key.startswith(prefix))


def _install_fake_mongodb(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeMongoClient()
    module = ModuleType("pymongo")
    module.MongoClient = lambda *_args, **_kwargs: client
    monkeypatch.setitem(sys.modules, "pymongo", module)


def _install_fake_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeRedisClient()

    class _RedisFactory:
        @staticmethod
        def from_url(*_args, **_kwargs) -> _FakeRedisClient:
            return client

    module = ModuleType("redis")
    module.Redis = _RedisFactory
    monkeypatch.setitem(sys.modules, "redis", module)


@pytest.mark.parametrize(
    "memory_cls,graph_cls,connection_string,install_backend,clear_backends",
    [
        (
            MongoDBMemoryStore,
            MongoDBGraphStore,
            "mongodb://localhost:27017/cellin",
            _install_fake_mongodb,
            mongodb_stores._BACKENDS.clear,
        ),
        (
            RedisMemoryStore,
            RedisGraphStore,
            "redis://localhost:6379/0",
            _install_fake_redis,
            redis_stores._BACKENDS.clear,
        ),
    ],
)
def test_document_and_cache_backends_share_memory_store_and_filter_archived_edges(
    memory_cls: type,
    graph_cls: type,
    connection_string: str,
    install_backend: Callable[[pytest.MonkeyPatch], None],
    clear_backends: Callable[[], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_backends()
    install_backend(monkeypatch)

    active = _edge("edge-active", "memory-1", "memory-2", archived=False)
    archived = _edge("edge-archived", "memory-1", "memory-3", archived=True)
    support_memory = _memory("support-memory", "Support memory")

    memory_store = memory_cls(connection_string)
    graph_store = graph_cls(connection_string)

    memory_store.put(_memory("memory-1", "Atlas memory"))
    memory_store.put(_memory("memory-2", "Second memory"))
    memory_store.put_many(())
    graph_store.upsert_edges((active, archived))
    graph_store.upsert_memories((support_memory,))
    graph_store.upsert_edge(active)
    graph_store.upsert_edges(())

    assert memory_store.get("memory-1") == _memory("memory-1", "Atlas memory")
    assert memory_store.get("missing-memory") is None
    assert graph_store.get_memory("memory-1") == _memory("memory-1", "Atlas memory")
    assert graph_store.neighbors("memory-1") == (active,)
    assert graph_store.list_edges() == (active,)
    assert graph_store.shares_memory_store(memory_store)
    assert memory_store.list() == (
        _memory("memory-1", "Atlas memory"),
        _memory("memory-2", "Second memory"),
        _memory("support-memory", "Support memory"),
    )

    duplicate_memory_store = memory_cls(connection_string)
    duplicate_graph_store = graph_cls(connection_string)
    duplicate_graph_store.upsert_memory(_memory("memory-1", "Atlas revised"))
    duplicate_memory_store.put(_memory("memory-3", "Third memory"))

    assert duplicate_graph_store.shares_memory_store(duplicate_memory_store)
    assert duplicate_graph_store.shares_memory_store(memory_store)
    assert memory_store.get("memory-1").text == "Atlas revised"
    assert duplicate_memory_store.get("memory-3") == _memory("memory-3", "Third memory")
