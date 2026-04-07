"""Additional coverage for SQLite stores and the in-memory vector index."""

from __future__ import annotations

import builtins
import math
import sys
from datetime import UTC, datetime

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
from cellin.stores import (
    InMemoryVectorIndex,
    PGVectorStore,
    SQLiteGraphStore,
    SQLiteMemoryStore,
    SQLiteVecStore,
)
from cellin.stores.vector_utils import cosine_similarity, vectorize


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


def test_sqlite_store_handles_empty_batches_missing_rows_and_batched_memory_upserts(
    tmp_path,
) -> None:
    database_path = tmp_path / "cellin.sqlite"
    memory_store = SQLiteMemoryStore(str(database_path))
    graph_store = SQLiteGraphStore(str(database_path))
    memory = _memory("atlas-1", "Atlas memory")

    memory_store.put_many(())
    graph_store.upsert_edges(())

    assert memory_store.get("missing") is None
    assert graph_store.list_edges() == ()

    graph_store.upsert_memories((memory,))

    assert graph_store.get_memory(memory.memory_id) == memory


def test_sqlite_store_filters_archived_edges_and_vector_index_handles_empty_text(
    tmp_path,
) -> None:
    database_path = tmp_path / "graph.sqlite"
    graph_store = SQLiteGraphStore(str(database_path))
    active = _edge("active-edge", "atlas-1", "atlas-2", archived=False)
    archived = _edge("archived-edge", "atlas-1", "atlas-3", archived=True)

    graph_store.upsert_edge(active)
    graph_store.upsert_edge(archived)

    assert graph_store.neighbors("atlas-1") == (active,)
    assert graph_store.list_edges() == (active,)

    vector_index = InMemoryVectorIndex()
    vector_index.upsert("blank", "")

    assert math.isclose(vector_index.search("", limit=1)[0].score, 0.0, abs_tol=1e-12)


def test_sqlite_vec_store_persists_vectors_and_supports_similarity_ranking(tmp_path) -> None:
    database_path = tmp_path / "vector.sqlite"
    vector_store = SQLiteVecStore(str(database_path))

    vector_store.upsert("m1", "atlas architecture graph")
    vector_store.upsert("m2", "gardening and tomatoes")
    vector_store.upsert("m3", "memory graph retrieval")

    query = "atlas graph"
    query_vector = vectorize(query)
    ranked = sorted(
        (
            ("m1", cosine_similarity(query_vector, vectorize("atlas architecture graph"))),
            ("m2", cosine_similarity(query_vector, vectorize("gardening and tomatoes"))),
            ("m3", cosine_similarity(query_vector, vectorize("memory graph retrieval"))),
        ),
        key=lambda item: (-item[1], item[0]),
    )
    expected = tuple(memory_id for memory_id, _ in ranked)

    results = vector_store.search(query, limit=3)

    assert tuple(result.memory_id for result in results) == expected
    assert results[0].score >= results[1].score


def test_sqlite_vec_store_respects_search_limit_zero(tmp_path) -> None:
    database_path = tmp_path / "vector.sqlite"
    vector_store = SQLiteVecStore(str(database_path))
    vector_store.upsert("m1", "atlas")

    assert vector_store.search("atlas", limit=0) == ()


def test_in_memory_vector_index_respects_limit_zero() -> None:
    vector_index = InMemoryVectorIndex()
    vector_index.upsert("m1", "atlas architecture")

    assert vector_index.search("atlas", limit=0) == ()


def test_vector_utils_handles_empty_vectors() -> None:
    assert cosine_similarity((), vectorize("atlas architecture")) == pytest.approx(0.0)


class _FakeResult:
    def __init__(self, rows: list[tuple[str, float]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple[str, float]]:
        return list(self._rows)


class _FakeConnection:
    def __init__(self, rows: list[tuple[str, float]], calls: list[tuple[str, object]]) -> None:
        self._rows = rows
        self._calls = calls

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        del exc_type, exc, tb
        return False

    def execute(self, query: str, params: object = None) -> _FakeResult:
        self._calls.append((query, params))
        if "SELECT memory_id, vector <=>" in query:
            return _FakeResult(self._rows)
        return _FakeResult([])


class _FakePsycopg:
    def __init__(self, rows: list[tuple[str, float]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, object]] = []
        self.connection_strings: list[str] = []

    def connect(self, connection_string: str) -> _FakeConnection:
        self.connection_strings.append(connection_string)
        return _FakeConnection(self.rows, self.calls)


def test_pgvector_store_requires_psycopg_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def _missing_psycopg(
        name: str,
        globals: object = None,
        locals: object = None,
        fromlist: object = (),
        level: int = 0,
    ) -> object:
        if name == "psycopg":
            raise ImportError("psycopg is unavailable")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.delitem(sys.modules, "psycopg", raising=False)
    monkeypatch.setattr(builtins, "__import__", _missing_psycopg)

    with pytest.raises(RuntimeError, match="psycopg"):
        PGVectorStore("postgresql://cellin/test")


def test_pgvector_store_creates_schema_upserts_and_searches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_psycopg = _FakePsycopg([("m1", 0.1), ("m2", 1.4)])
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)

    vector_store = PGVectorStore("postgresql://cellin/test", table_name="cellin_vectors_test")
    vector_store.upsert("m1", "atlas architecture graph")
    results = vector_store.search("atlas graph", limit=2)

    assert fake_psycopg.connection_strings == ["postgresql://cellin/test"] * 3
    queries = [query for query, _ in fake_psycopg.calls]
    assert any("CREATE TABLE IF NOT EXISTS cellin_vectors_test" in query for query in queries)
    assert any("INSERT INTO cellin_vectors_test" in query for query in queries)
    assert any("SELECT memory_id, vector <=> %s AS distance" in query for query in queries)
    assert tuple(result.memory_id for result in results) == ("m1", "m2")
    assert results[0].score == pytest.approx(0.9)
    assert results[1].score == pytest.approx(0.0)


def test_pgvector_store_limit_zero_short_circuits(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_psycopg = _FakePsycopg([("m1", 0.1)])
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)

    vector_store = PGVectorStore("postgresql://cellin/test")

    assert vector_store.search("atlas graph", limit=0) == ()
    assert len(fake_psycopg.calls) == 1


def test_in_memory_vector_index_respects_search_limit_zero() -> None:
    vector_index = InMemoryVectorIndex()
    vector_index.upsert("memory-1", "atlas architecture")
    assert vector_index.search("atlas", limit=0) == ()


def test_cosine_similarity_returns_zero_for_empty_vectors() -> None:
    assert math.isclose(cosine_similarity((), ()), 0.0, abs_tol=1e-12)
    assert math.isclose(cosine_similarity((), (1.0, 0.0)), 0.0, abs_tol=1e-12)
