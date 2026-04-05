"""Coverage-focused tests for the optional pgvector backend."""

from __future__ import annotations

import builtins
import sys
from types import ModuleType

import pytest

from cellin.stores import PGVectorStore
from cellin.stores.vector_utils import cosine_similarity


class _FakePgvectorConnection:
    def __init__(self, backend: _FakePgvectorBackend) -> None:
        self._backend = backend
        self._rows: list[tuple[str, float]] = []

    def __enter__(self) -> _FakePgvectorConnection:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def execute(self, query: str, params: tuple[object, ...] = ()) -> _FakePgvectorConnection:
        if "CREATE TABLE" in query:
            return self

        if "INSERT INTO" in query:
            memory_id = str(params[0])
            vector = tuple(params[1])  # type: ignore[arg-type]
            self._backend._vectors[memory_id] = vector
            return self

        if "SELECT memory_id" in query:
            query_vector = tuple(params[0]) if params else ()
            limit = int(params[1]) if len(params) > 1 else len(self._backend._vectors)
            rows = []
            for memory_id, vector in self._backend._vectors.items():
                distance = 1.0 - cosine_similarity(query_vector, vector)
                rows.append((memory_id, max(distance, 0.0)))
            rows.sort(key=lambda item: (item[1], item[0]))
            self._rows = rows[: max(0, limit)]
            return self

        return self

    def fetchall(self) -> list[tuple[str, float]]:
        return list(self._rows)


class _FakePgvectorBackend:
    def __init__(self) -> None:
        self._vectors: dict[str, tuple[float, ...]] = {}

    def connect(self, connection_string: str) -> _FakePgvectorConnection:
        del connection_string
        return _FakePgvectorConnection(self)


def test_pgvector_store_requires_psycopg_dependency(monkeypatch) -> None:
    original_import = builtins.__import__

    def _missing_psycopg(
        name: str,
        *args: object,  # pragma: no cover - import hook compatibility
    ) -> object:
        if name == "psycopg":
            raise ModuleNotFoundError("No module named psycopg")
        return original_import(name, *args)

    try:
        monkeypatch.setattr("builtins.__import__", _missing_psycopg)
        with pytest.raises(RuntimeError, match="pgvector backend requires optional dependency"):
            PGVectorStore("postgres://invalid")
    finally:
        monkeypatch.setattr("builtins.__import__", original_import)


def test_pgvector_store_supports_upsert_and_search() -> None:
    fake_backend = _FakePgvectorBackend()
    fake_module = ModuleType("psycopg")
    fake_module.connect = fake_backend.connect
    original_psycopg = sys.modules.get("psycopg")
    try:
        sys.modules["psycopg"] = fake_module
        vector_store = PGVectorStore("postgres://local")
        vector_store.upsert("m1", "atlas architecture and graphs")
        vector_store.upsert("m2", "gardening and tomatoes")

        ranked = vector_store.search("atlas architecture", limit=2)
        assert tuple(match.memory_id for match in ranked) == ("m1", "m2")
        assert ranked[0].score >= ranked[1].score
    finally:
        if original_psycopg is None:
            sys.modules.pop("psycopg", None)
        else:
            sys.modules["psycopg"] = original_psycopg
