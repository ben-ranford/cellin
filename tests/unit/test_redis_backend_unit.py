"""Unit tests for the Redis backend edge index (O(degree) neighbors)."""

from __future__ import annotations

from datetime import UTC, datetime

from cellin.core import (
    EdgeKind,
    MemoryEdge,
    Provenance,
)
from cellin.stores import redis as redis_module
from cellin.stores._graph_serialization import dump_edge


def _edge(edge_id: str, source_id: str, target_id: str, *, archived: bool = False) -> MemoryEdge:
    return MemoryEdge(
        edge_id=edge_id,
        source_id=source_id,
        target_id=target_id,
        kind=EdgeKind.SUPPORTS,
        provenance=Provenance(source_id=edge_id, source_type="fixture"),
        created_at=datetime(2026, 4, 22, tzinfo=UTC),
        metadata={"archived": archived},
    )


class _FakeRedis:
    """Minimal fake Redis client with a tracked call log."""

    def __init__(self) -> None:
        self._strings: dict[str, str] = {}
        self._sets: dict[str, set[str]] = {}
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def set(self, key: str, value: str) -> None:
        self.calls.append(("set", (key, value)))
        self._strings[key] = value

    def get(self, key: str) -> str | None:
        self.calls.append(("get", (key,)))
        return self._strings.get(key)

    def sadd(self, key: str, *members: str) -> int:
        self.calls.append(("sadd", (key, *members)))
        s = self._sets.setdefault(key, set())
        added = len(set(members) - s)
        s.update(members)
        return added

    def smembers(self, key: str) -> set[str]:
        self.calls.append(("smembers", (key,)))
        return set(self._sets.get(key, set()))

    def scan_iter(self, match: str) -> list[str]:
        self.calls.append(("scan_iter", (match,)))
        import fnmatch

        return [k for k in self._strings if fnmatch.fnmatch(k, match)]


def _make_backend(fake_client: _FakeRedis) -> redis_module._RedisBackend:
    """Build a _RedisBackend whose _client is replaced with the fake."""
    # Bypass __init__ entirely to avoid importing the real `redis` package.
    backend = object.__new__(redis_module._RedisBackend)
    backend._client = fake_client  # type: ignore[attr-defined]
    backend._namespace = "cellin:0"
    return backend


def test_upsert_edges_populates_index_sets() -> None:
    fake = _FakeRedis()
    backend = _make_backend(fake)

    e1 = _edge("edge-1", "memory-a", "memory-b")
    e2 = _edge("edge-2", "memory-c", "memory-a")

    backend.upsert_edges((e1, e2))

    # Both edges should have been stored by key
    assert fake._strings["cellin:0:edge:edge-1"] == dump_edge(e1)
    assert fake._strings["cellin:0:edge:edge-2"] == dump_edge(e2)

    # Index sets: edge-by-src keyed on source_id
    assert "edge-1" in fake._sets["cellin:0:edge-by-src:memory-a"]
    assert "edge-2" in fake._sets["cellin:0:edge-by-src:memory-c"]

    # Index sets: edge-by-tgt keyed on target_id
    assert "edge-1" in fake._sets["cellin:0:edge-by-tgt:memory-b"]
    assert "edge-2" in fake._sets["cellin:0:edge-by-tgt:memory-a"]


def test_neighbors_returns_correct_edges_without_scan() -> None:
    fake = _FakeRedis()
    backend = _make_backend(fake)

    e_src = _edge("edge-src", "memory-x", "memory-y")  # memory-x is the source
    e_tgt = _edge("edge-tgt", "memory-z", "memory-x")  # memory-x is the target
    e_other = _edge("edge-other", "memory-y", "memory-z")  # unrelated

    backend.upsert_edges((e_src, e_tgt, e_other))

    # Clear the call log so we can inspect only the neighbors() call.
    fake.calls.clear()

    result = backend.neighbors("memory-x")

    assert {e.edge_id for e in result} == {"edge-src", "edge-tgt"}

    # SCAN must NOT have been called during neighbors()
    scan_calls = [c for c in fake.calls if c[0] == "scan_iter"]
    assert scan_calls == [], f"Unexpected scan_iter calls: {scan_calls}"


def test_neighbors_excludes_archived_edges() -> None:
    fake = _FakeRedis()
    backend = _make_backend(fake)

    active = _edge("edge-active", "memory-m", "memory-n", archived=False)
    archived = _edge("edge-archived", "memory-m", "memory-p", archived=True)

    backend.upsert_edges((active, archived))
    result = backend.neighbors("memory-m")

    assert len(result) == 1
    assert result[0].edge_id == "edge-active"


def test_neighbors_returns_empty_for_unknown_memory() -> None:
    fake = _FakeRedis()
    backend = _make_backend(fake)

    result = backend.neighbors("no-such-memory")

    assert result == ()
    scan_calls = [c for c in fake.calls if c[0] == "scan_iter"]
    assert scan_calls == []
