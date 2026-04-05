"""Unit tests for MongoDB and Redis backend helpers."""

from __future__ import annotations

import builtins
import sys

import pytest

from cellin.stores import mongodb as mongodb_stores
from cellin.stores import redis as redis_stores


def test_document_and_cache_backends_require_optional_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__

    def _missing_backend(
        name: str,
        globals: object | None = None,
        locals: object | None = None,
        fromlist: tuple[object, ...] | None = (),
        level: int = 0,
    ) -> object:
        if name in {"pymongo", "redis"}:
            raise ModuleNotFoundError(f"No module named {name}")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.delitem(sys.modules, "pymongo", raising=False)
    monkeypatch.delitem(sys.modules, "redis", raising=False)
    monkeypatch.setattr(builtins, "__import__", _missing_backend)

    with pytest.raises(
        mongodb_stores._MissingMongoDependencyError,
        match="mongodb backend requires optional dependency `pymongo`",
    ):
        mongodb_stores._MongoBackend("mongodb://localhost:27017/cellin")

    with pytest.raises(
        redis_stores._MissingRedisDependencyError,
        match="redis backend requires optional dependency `redis`",
    ):
        redis_stores._RedisBackend("redis://localhost:6379/0")


def test_document_and_cache_backend_namespaces_default_safely() -> None:
    assert mongodb_stores._database_name("mongodb://localhost:27017") == "cellin"
    assert mongodb_stores._database_name("mongodb://localhost:27017/runtime") == "runtime"
    assert redis_stores._redis_namespace("redis://localhost:6379") == "cellin:0"
    assert redis_stores._redis_namespace("redis://localhost:6379/9") == "cellin:9"
