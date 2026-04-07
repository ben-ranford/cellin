"""Integration-focused coverage for remote vector backends with mocked dependencies."""

from __future__ import annotations

import json
import sys
from types import ModuleType
from typing import Any
from urllib.parse import urlunsplit

import pytest

from cellin.core import VectorMatch
from cellin.stores import (
    MilvusVectorStore,
    PineconeVectorStore,
    QdrantVectorStore,
    RedisVectorStore,
    WeaviateVectorStore,
)
from cellin.stores import milvus as milvus_store
from cellin.stores import pinecone as pinecone_store
from cellin.stores import qdrant as qdrant_store
from cellin.stores import redis_vector as redis_vector_store
from cellin.stores import weaviate as weaviate_store


def _module_name(value: str, module: ModuleType) -> None:
    sys.modules[value] = module


def _install_qdrant(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {
        "collections": set(),
        "points": {},
        "create_collection_calls": 0,
        "upsert_calls": 0,
    }

    class _VectorParams:
        def __init__(self, size: int, distance: str) -> None:
            self.size = size
            self.distance = distance

    class _Distance:
        COSINE = "cosine"

    class _Models:
        vector_params = _VectorParams
        distance = _Distance

    class _Response:
        def __init__(self, collections: list[str]) -> None:
            self.collections = [
                type("collection", (), {"name": collection_name}) for collection_name in collections
            ]

    class _QdrantClient:
        def __init__(self, url: str | None = None) -> None:
            self.url = url

        def get_collections(self) -> _Response:
            return _Response(sorted(state["collections"]))

        def create_collection(self, collection_name: str, vectors_config: object) -> None:
            del vectors_config
            state["collections"].add(collection_name)
            state["create_collection_calls"] += 1

        def upsert(
            self, collection_name: str, points: list[dict[str, object]], wait: bool = False
        ) -> None:
            del wait
            collection = state["points"].setdefault(collection_name, {})
            for point in points:
                memory_id = str(point.get("id", ""))
                collection[memory_id] = point
                state["upsert_calls"] += 1

        def query_points(
            self,
            collection_name: str,
            query: object,
            limit: int,
            with_payload: bool = True,
            with_vectors: bool = True,
            query_filter: object | None = None,
            **_: object,
        ) -> object:
            del query, with_payload, with_vectors, query_filter
            points = [
                type(
                    "point",
                    (),
                    {
                        "id": memory_id,
                        "payload": {
                            "memory_id": memory_id,
                            "archived": bool(payload["payload"]["archived"]),
                        },
                        "vector": payload["payload"]["vector"],
                        "score": 1.0 - index * 0.1,
                    },
                )
                for index, (memory_id, payload) in enumerate(
                    state["points"].get(collection_name, {}).items()
                )
            ]
            return type(
                "response",
                (),
                {"points": points[:limit]},
            )

    qdrant_module = ModuleType("qdrant_client")
    http_module = ModuleType("qdrant_client.http")
    models_module = ModuleType("qdrant_client.http.models")
    models_module.VectorParams = _Models.vector_params
    models_module.Distance = _Models.distance
    http_module.models = models_module

    qdrant_module.QdrantClient = _QdrantClient
    qdrant_module.http = http_module
    _module_name("qdrant_client", qdrant_module)
    _module_name("qdrant_client.http", http_module)
    _module_name("qdrant_client.http.models", models_module)

    monkeypatch.setitem(sys.modules, "qdrant_client", qdrant_module)
    monkeypatch.setitem(sys.modules, "qdrant_client.http", http_module)
    monkeypatch.setitem(sys.modules, "qdrant_client.http.models", models_module)
    return state


def test_qdrant_vector_store_remains_tombstone_safe_with_idempotent_init(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_qdrant(monkeypatch)

    store = QdrantVectorStore("qdrant://localhost:6333/cellin_vectors")
    peer_store = QdrantVectorStore("qdrant://localhost:6333/cellin_vectors")
    assert store._backend is peer_store._backend

    store.upsert("memory-1", "atlas architecture")
    store.upsert("memory-2", "gardening and tomatoes")
    store.delete("memory-2")

    matches = store.search("atlas", limit=10)
    memory_ids = tuple(match.memory_id for match in matches)
    assert "memory-1" in memory_ids
    assert "memory-2" not in memory_ids


def _install_weaviate(
    monkeypatch: pytest.MonkeyPatch,
    *,
    include_collections: bool = True,
    include_schema: bool = True,
    schema_payload: Any | None = None,
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "collections": set(),
        "rows": {},
        "collection_calls": 0,
        "classes": set(),
    }

    class _QueryResult:
        def __init__(self, objects: list[object]) -> None:
            self.objects = objects

    class _Object:
        def __init__(self, memory_id: str, archived: bool) -> None:
            self.properties = {"memory_id": memory_id, "archived": archived}
            self.metadata = type("metadata", (), {"certainty": 1.0})()

    class _Collections:
        def exists(self, name: str) -> bool:
            return name in state["collections"]

        def create(self, name: str, properties: list[dict[str, str]]) -> None:
            del properties
            state["collections"].add(name)

        def get(self, name: str) -> object:
            return _Collection(name)

    class _CollectionData:
        def __init__(self, collection: _Collection) -> None:
            self._collection = collection

        def insert(self, properties: dict[str, object], vector: list[float], **_: object) -> None:
            del vector
            memory_id = str(properties.get("memory_id"))
            self._collection.rows[memory_id] = bool(properties.get("archived", False))

    class _CollectionQuery:
        def __init__(self, collection: _Collection) -> None:
            self._collection = collection

        def near_vector(self, **_: object) -> _QueryResult:
            del _
            objects = [
                _Object(memory_id=memory_id, archived=archived)
                for memory_id, archived in self._collection.rows.items()
            ]
            return _QueryResult(objects)

    class _Collection:
        def __init__(self, name: str) -> None:
            self.name = name
            self.rows = state["rows"].setdefault(name, {})

        @property
        def data(self) -> _CollectionData:
            return _CollectionData(self)

        @property
        def query(self) -> _CollectionQuery:
            return _CollectionQuery(self)

    class _Schema:
        def get(self) -> dict[str, object]:
            if schema_payload is not None:
                return schema_payload
            return {"classes": [{"class": class_name} for class_name in state["classes"]]}

        def create_class(self, definition: dict[str, object]) -> None:
            state["classes"].add(str(definition.get("class", "")))

        def __getattr__(self, name: str) -> None:
            raise AttributeError(name)

    class _Client:
        def __init__(self, url: str | None = None) -> None:
            del url
            self.collections = _Collections() if include_collections else None
            self.schema = _Schema() if include_schema else None

    weaviate_module = ModuleType("weaviate")
    weaviate_module.Client = _Client

    monkeypatch.setitem(sys.modules, "weaviate", weaviate_module)

    return state


def test_weaviate_vector_store_filters_archived_records_and_idempotent_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_weaviate(monkeypatch)

    store = WeaviateVectorStore("https://localhost:8080/cellin_vectors")
    backup = WeaviateVectorStore("https://localhost:8080/cellin_vectors")
    assert store._backend is backup._backend

    store.upsert("memory-1", "atlas architecture")
    store.upsert("memory-2", "gardening")
    store.delete("memory-2")

    result = store.search("query", limit=10)
    memory_ids = tuple(match.memory_id for match in result)
    assert "memory-1" in memory_ids
    assert "memory-2" not in memory_ids


def test_weaviate_normalization_supports_no_scheme_endpoints() -> None:
    endpoint, collection = weaviate_store._normalize_connection_and_collection(
        "?collection=cellin_vectors"
    )
    assert endpoint == ""
    assert collection == "cellin_vectors"


def test_weaviate_falls_back_to_schema_init_when_collections_api_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    weaviate_store._BACKENDS.clear()
    state = _install_weaviate(monkeypatch, include_collections=False)

    store = WeaviateVectorStore("https://localhost:8080/?collection=weaviate_schema")
    store.upsert("memory-1", "atlas architecture")
    store.delete("memory-1")

    assert "weaviate_schema" in state["classes"]


def test_weaviate_vector_coerce_vector_handles_iterable_and_mapping_fallbacks() -> None:
    assert weaviate_store._coerce_vector("bad") == ()
    assert weaviate_store._coerce_vector(("1", "2", "3")) == (1.0, 2.0, 3.0)


def test_weaviate_ensure_collection_exists_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_weaviate(monkeypatch)
    store = WeaviateVectorStore("https://localhost:8080/?collection=weaviate_initialized")
    backend = store._backend
    backend._ensure_collection_exists()


def test_weaviate_ensures_collection_without_collections_or_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_weaviate(monkeypatch, include_collections=False, include_schema=False)
    store = WeaviateVectorStore("https://localhost:8080/?collection=weaviate_no_api")
    assert store._backend._initialized is True


def test_weaviate_ignores_invalid_schema_class_payloads(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _install_weaviate(
        monkeypatch,
        include_collections=False,
        schema_payload={"classes": "bad"},
    )
    store = WeaviateVectorStore("https://localhost:8080/?collection=weaviate_bad_schema")
    backend = store._backend
    assert "weaviate_bad_schema" in state["classes"]
    assert backend._initialized is True


def test_weaviate_uses_positional_insert_call_on_typeerror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    weaviate_store._BACKENDS.clear()
    _install_weaviate(monkeypatch)
    store = WeaviateVectorStore("https://localhost:8080/?collection=weaviate_legacy_insert")
    backend = store._backend
    collection = backend._active_collection()
    original_insert = type(collection.data).insert
    calls: dict[str, bool] = {"fallback": False}

    def insert(*args: object, **kwargs: object) -> None:
        if "properties" in kwargs:
            calls["fallback"] = True
            raise TypeError("legacy insert signature")
        original_insert(*args, **kwargs)

    monkeypatch.setattr(type(collection.data), "insert", insert)
    store.upsert("memory-1", "atlas architecture")
    assert calls["fallback"] is True


def test_weaviate_upsert_falls_back_to_data_object_create_when_collection_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_weaviate(monkeypatch, include_collections=False)
    store = WeaviateVectorStore("https://localhost:8080/?collection=weaviate_data_object")
    backend = store._backend
    create_calls: dict[str, int] = {"calls": 0}

    class _DataObject:
        def create(self, **kwargs: object) -> None:
            del kwargs
            create_calls["calls"] += 1

    backend._active_collection = lambda: None  # type: ignore[method-assign]
    backend._client.data_object = _DataObject()

    store.upsert("memory-1", "atlas architecture")
    assert create_calls["calls"] == 1


def test_weaviate_query_objects_returns_empty_for_non_iterable_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_weaviate(monkeypatch)
    store = WeaviateVectorStore("https://localhost:8080/?collection=cellin_vectors")
    backend = store._backend

    collection = type(
        "Collection",
        (),
        {
            "query": type(
                "Query",
                (),
                {
                    "near_vector": lambda self, **kwargs: type(
                        "Response", (), {"objects": "not-list"}
                    )()
                },
            )()
        },
    )()
    assert backend._query_objects(collection, (0.0, 0.0, 0.0), 5) == []


def test_weaviate_query_collection_returns_empty_without_active_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_weaviate(monkeypatch)
    store = WeaviateVectorStore("https://localhost:8080/?collection=cellin_vectors")
    backend = store._backend
    backend._active_collection = lambda: None  # type: ignore[method-assign]
    assert backend._query_collection((0.0, 0.0, 0.0), 5) == []


def test_weaviate_query_fallback_executes_with_query_client_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_weaviate(monkeypatch)
    backend = WeaviateVectorStore("https://localhost:8080/?collection=cellin_vectors")._backend
    backend._client.query = object()
    assert backend._query_fallback((0.0, 0.0, 0.0), 5) == []


def test_weaviate_search_merges_query_and_local_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    weaviate_store._BACKENDS.clear()
    _install_weaviate(monkeypatch)
    store = WeaviateVectorStore("https://localhost:8080/?collection=cellin_vectors")
    backend = store._backend

    backend._query_collection = lambda _vector, limit: [
        VectorMatch(memory_id="collection-1", score=0.9),
    ]
    backend._query_fallback = lambda _vector, limit: [
        VectorMatch(memory_id="fallback-1", score=0.5),
        VectorMatch(memory_id="collection-1", score=0.1),
    ]

    store._backend._vectors["collection-1"] = store._backend._vectors.get(
        "collection-1", (0.0,) * 12
    )
    store._backend._vectors["local-only"] = (0.0,) * 12
    matches = store.search("query", limit=10)
    ids = tuple(match.memory_id for match in matches)
    assert ids == ("collection-1", "fallback-1", "local-only")


def test_weaviate_query_fallback_keeps_empty_result_when_query_api_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    weaviate_store._BACKENDS.clear()
    _install_weaviate(monkeypatch)
    store = WeaviateVectorStore("https://localhost:8080/cellin_vectors")
    backend = store._backend
    matches = backend._query_fallback((0.0, 0.0, 0.0), 5)
    assert matches == []


def test_qdrant_backend_supports_no_scheme_endpoints_and_zero_limit_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_qdrant(monkeypatch)

    endpoint, collection = qdrant_store._normalize_connection_and_collection(
        "?collection=cellin_vectors"
    )
    assert endpoint == ""
    assert collection == "cellin_vectors"

    store = QdrantVectorStore("?collection=cellin_vectors")
    assert store.search("query", limit=0) == ()


def test_qdrant_vector_store_supports_legacy_query_filter_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_qdrant(monkeypatch)

    store = QdrantVectorStore("qdrant://localhost:6333/cellin_vectors")
    store.upsert("memory-1", "atlas architecture")

    backend = store._backend
    original_query = backend._client.query_points

    first_call = {"count": 0}

    def legacy_query(*args: object, **kwargs: object) -> object:
        del args
        if "query_filter" in kwargs and first_call["count"] == 0:
            first_call["count"] += 1
            raise TypeError("qdrant 1.0 compatibility")
        return original_query(**kwargs)

    monkeypatch.setattr(backend._client, "query_points", legacy_query)

    results = store.search("atlas", limit=10)
    assert first_call["count"] == 1
    assert tuple(item.memory_id for item in results) == ("memory-1",)


def test_qdrant_search_uses_local_matches_when_remote_query_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_qdrant(monkeypatch)

    store = QdrantVectorStore("qdrant://localhost:6333/cellin_vectors")
    store.upsert("memory-1", "atlas architecture")

    backend = store._backend
    def query_points(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise RuntimeError("qdrant unavailable")

    monkeypatch.setattr(backend._client, "query_points", query_points)

    assert tuple(item.memory_id for item in store.search("atlas", limit=10)) == ("memory-1",)


def test_qdrant_vector_payload_helpers_handle_fallback_types() -> None:
    assert qdrant_store._coerce_vector("hello") == ()
    assert qdrant_store._coerce_vector(("1", "2")) == (1.0, 2.0)
    assert qdrant_store._coerce_vector(["bad", 1.0]) == ()
    assert qdrant_store._extract_payload(object()) == {}


def test_qdrant_extract_payload_accepts_mapping_point() -> None:
    assert qdrant_store._extract_payload({"memory_id": "mapped"}) == {"memory_id": "mapped"}


def test_qdrant_collection_initialization_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _install_qdrant(monkeypatch)
    qdrant_store._BACKENDS.clear()
    store = QdrantVectorStore("qdrant://localhost:6333/?collection=qdrant_init")
    backend = store._backend
    assert state["create_collection_calls"] == 1
    backend._ensure_collection_exists()
    assert state["create_collection_calls"] == 1


def test_qdrant_query_remote_skips_empty_ids_and_scores_zero_vectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_qdrant(monkeypatch)

    store = QdrantVectorStore("qdrant://localhost:6333/cellin_vectors")
    backend = store._backend

    class _RemotePoint:
        def __init__(self, memory_id: str, vector: tuple[float, ...], score: float = 0.0) -> None:
            self.id = memory_id
            self.payload = {"memory_id": memory_id, "archived": False}
            self.vector = list(vector)
            self.score = score

    def remote_query(*_: object, **__: object) -> object:
        del _, __
        response = type(
            "response",
            (),
            {
                "points": (
                    _RemotePoint(
                        memory_id="",
                        vector=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
                        score=0.0,
                    ),
                    _RemotePoint(
                        memory_id="vector-only",
                        vector=(
                            1.0,
                            0.0,
                            0.0,
                            0.0,
                            0.0,
                            0.0,
                            0.0,
                            0.0,
                            0.0,
                            0.0,
                            0.0,
                            0.0,
                        ),
                        score=0.0,
                    ),
                )
            },
        )
        return response

    monkeypatch.setattr(backend._client, "query_points", remote_query)
    matches = backend._query_remote(
        (
            1.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
        ),
        limit=5,
    )
    assert tuple(match.memory_id for match in matches) == ("vector-only",)


def _install_pinecone(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {
        "indexes": set(),
        "points": {},
        "create_calls": 0,
    }

    class _Index:
        def __init__(self, name: str) -> None:
            self.name = name

        def upsert(self, vectors: list[dict[str, object]], namespace: str = "default") -> None:
            by_namespace = state["points"].setdefault((self.name, namespace), {})
            for item in vectors:
                by_namespace[str(item["id"])] = item

        def query(self, **kwargs: object) -> object:
            namespace = str(kwargs.get("namespace", "default"))
            by_namespace = state["points"].get((self.name, namespace), {})
            matches = [
                type(
                    "match",
                    (),
                    {
                        "id": memory_id,
                        "score": 1.0 - index * 0.1,
                        "metadata": dict(item["metadata"]),
                    },
                )
                for index, (memory_id, item) in enumerate(by_namespace.items())
            ]
            return type("response", (), {"matches": matches[: int(kwargs.get("top_k", 10))]})

    class _PineconeIndexManager:
        def __init__(self, *_: object, **__: object) -> None:
            # Test double: construction only; no state to initialize.
            pass

        def index(self, name: str) -> _Index:
            return _Index(name)

        def __getattr__(self, name: str) -> Any:
            if name == "Index":
                return self.index
            raise AttributeError(name)

    def _list_indexes() -> list[str]:
        return list(state["indexes"])

    def _create_index(name: str, dimension: int, metric: str, **_: object) -> None:
        del dimension, metric
        state["create_calls"] = state["create_calls"] + 1
        state["indexes"].add(name)

    pinecone_module = ModuleType("pinecone")
    pinecone_module.Pinecone = _PineconeIndexManager
    pinecone_module.list_indexes = _list_indexes
    pinecone_module.create_index = _create_index
    pinecone_module.init = lambda **kwargs: None
    pinecone_module.Index = lambda name: _Index(name)

    monkeypatch.setitem(sys.modules, "pinecone", pinecone_module)
    return state


def test_pinecone_connection_parsing_supports_auth_and_no_scheme_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_pinecone(monkeypatch)

    username = "user"
    environment = "env"
    endpoint_url = urlunsplit(
        (
            "https",
            f"{username}:{environment}@localhost:8100",
            "/custom_index",
            "namespace=unit",
            "",
        )
    )
    endpoint, api_key, index, namespace = pinecone_store._normalize_connection_and_index(
        endpoint_url
    )
    expected_endpoint = urlunsplit(
        ("https", f"{username}:{environment}@localhost:8100", "", "", "")
    )
    assert endpoint == expected_endpoint
    assert api_key == "user"
    assert index == "custom_index"
    assert namespace == "unit"

    endpoint, api_key, index, namespace = pinecone_store._normalize_connection_and_index(
        "localhost:8100?index=alt_index"
    )
    assert endpoint == "localhost:8100"
    assert api_key is None
    assert index == "alt_index"


def test_pinecone_initialization_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _install_pinecone(monkeypatch)
    store = PineconeVectorStore("https://localhost:8100/?index=pinecone_init")
    assert state["create_calls"] == 1
    store._backend._ensure_index_exists()
    assert state["create_calls"] == 1


def test_pinecone_index_names_with_invalid_client_api_returns_empty_set() -> None:
    class _NoCallable:
        list_indexes = "not callable"

    assert pinecone_store._index_names(_NoCallable()) == set()


def test_pinecone_index_name_detection_is_compatible_with_set_and_dict_payloads() -> None:
    class _DictIndexes:
        def list_indexes(self) -> dict[str, list[str]]:
            return {"indexes": ["default", "memory_index"]}

    class _SetIndexes:
        def list_indexes(self) -> set[str]:
            return {"default", "memory_index"}

    class _ListIndexes:
        def list_indexes(self) -> list[str]:
            return ["default", "memory_index"]

    assert pinecone_store._index_names(_DictIndexes()) == {"default", "memory_index"}
    assert pinecone_store._index_names(_SetIndexes()) == {"default", "memory_index"}
    assert pinecone_store._index_names(_ListIndexes()) == {"default", "memory_index"}


def test_pinecone_query_uses_legacy_signature_when_filter_not_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_pinecone(monkeypatch)
    store = PineconeVectorStore("https://localhost:8100/cellin_vectors")
    store.upsert("memory-1", "atlas architecture")

    backend = store._backend
    original_query = backend._index.query
    first_call = {"count": 0}

    def legacy_query(**kwargs: object) -> object:
        if "filter" in kwargs and first_call["count"] == 0:
            first_call["count"] += 1
            raise TypeError("pinecone legacy query")
        return original_query(**kwargs)

    monkeypatch.setattr(backend._index, "query", legacy_query)

    assert tuple(item.memory_id for item in store.search("atlas", limit=10)) == ("memory-1",)
    assert first_call["count"] == 1


def test_pinecone_search_appends_local_matches_when_remote_returns_fewer_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_pinecone(monkeypatch)
    store = PineconeVectorStore("https://localhost:8100/cellin_vectors")
    store.upsert("memory-1", "atlas architecture")
    store.upsert("memory-2", "gardening")

    backend = store._backend

    def partial_query(**_: object) -> object:
        return type(
            "response",
            (),
            {
                "matches": [
                    type(
                        "match",
                        (),
                        {"id": "memory-1", "score": 0.42, "metadata": {"memory_id": "memory-1"}},
                    )
                ]
            },
        )

    monkeypatch.setattr(backend._index, "query", partial_query)
    matches = store.search("atlas", limit=10)
    assert tuple(match.memory_id for match in matches) == ("memory-1", "memory-2")


def test_pinecone_search_respects_zero_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_pinecone(monkeypatch)
    store = PineconeVectorStore("https://localhost:8100/cellin_vectors")
    assert store.search("query", limit=0) == ()


def test_pinecone_uses_init_path_when_pinecone_connector_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pinecone_store._BACKENDS.clear()
    _install_pinecone(monkeypatch)
    pinecone_module = sys.modules["pinecone"]
    monkeypatch.delattr(pinecone_module, "Pinecone", raising=False)

    state: dict[str, Any] = {"init_called": False}
    original_init = pinecone_module.init

    def init_with_state(**kwargs: object) -> None:
        state["init_called"] = True
        original_init(**kwargs)

    monkeypatch.setattr(pinecone_module, "init", init_with_state)
    PineconeVectorStore("https://localhost:8100/?collection=legacy_pinecone")

    assert state["init_called"] is True


def test_pinecone_vector_store_filters_tombstones_and_reuses_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_pinecone(monkeypatch)

    store = PineconeVectorStore("https://localhost:8100/cellin_vectors")
    peer = PineconeVectorStore("https://localhost:8100/cellin_vectors")
    assert store._backend is peer._backend

    store.upsert("memory-1", "atlas architecture")
    store.upsert("memory-2", "gardening")
    store.delete("memory-2")

    result = store.search("query", limit=10)
    memory_ids = tuple(match.memory_id for match in result)
    assert "memory-1" in memory_ids
    assert "memory-2" not in memory_ids


def _install_milvus(monkeypatch: pytest.MonkeyPatch) -> None:
    state: dict[str, Any] = {
        "collections": set(),
        "rows": {},
    }

    class _FakeDataType:
        VARCHAR = "varchar"
        FLOAT_VECTOR = "float_vector"
        BOOL = "bool"

    class _FieldSchema:
        def __init__(self, **kwargs: object) -> None:
            del kwargs

    class _CollectionSchema:
        def __init__(self, fields: tuple[object, ...]) -> None:
            del fields

    class _Match:
        def __init__(self, memory_id: str, archived: bool, score: float) -> None:
            self.id = memory_id
            self.score = score
            self.entity = {"memory_id": memory_id, "archived": archived}

    class _Collection:
        def __init__(self, name: str) -> None:
            self.name = name

        def insert(self, rows: list[object]) -> None:
            ids = rows[0]
            vectors = rows[1]
            archived = rows[2]
            for index, memory_id in enumerate(ids):
                memory = str(memory_id)
                state["rows"].setdefault(self.name, {})[memory] = (
                    vectors[index],
                    bool(archived[index]),
                )

        def search(self, **kwargs: object) -> list[list[_Match]]:
            del kwargs
            collection_rows = state["rows"].get(self.name, {})
            return [
                [
                    _Match(memory_id, archived, 1.0 - index * 0.1)
                    for index, (memory_id, (_, archived)) in enumerate(collection_rows.items())
                ]
            ]

    class _ConnectionManager:
        def connect(self, uri: str) -> None:
            del uri

    def _has_collection(name: str) -> bool:
        return name in state["collections"]

    def _factory_connection(collection_name: str, **_: object) -> _Collection:
        return _Collection(collection_name)

    milvus_module = ModuleType("pymilvus")
    milvus_module.Collection = _factory_connection
    milvus_module.CollectionSchema = _CollectionSchema
    milvus_module.DataType = _FakeDataType
    milvus_module.FieldSchema = _FieldSchema
    milvus_module.connections = _ConnectionManager()
    milvus_module.utility = type("util", (), {"has_collection": staticmethod(_has_collection)})()

    monkeypatch.setitem(sys.modules, "pymilvus", milvus_module)


def test_milvus_normalization_supports_no_scheme_endpoints() -> None:
    endpoint, collection = milvus_store._normalize_connection_and_collection(
        "?collection=cellin_vectors"
    )
    assert endpoint == ""
    assert collection == "cellin_vectors"


def test_milvus_vector_store_supports_upsert_search_delete_and_shared_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_milvus(monkeypatch)

    store = MilvusVectorStore("https://localhost:19530/cellin_vectors")
    peer = MilvusVectorStore("https://localhost:19530/cellin_vectors")
    assert store._backend is peer._backend

    store.upsert("memory-1", "atlas architecture")
    store.upsert("memory-2", "gardening")
    store.delete("memory-2")

    memory_ids = tuple(item.memory_id for item in store.search("query", limit=10))
    assert "memory-1" in memory_ids
    assert "memory-2" not in memory_ids


def test_milvus_row_entities_falls_back_when_hit_entity_payload_is_uncoercible() -> None:
    class _Hit:
        pass

    hit = _Hit()
    hit.entity = object()
    hit.memory_id = "fallback-memory"

    memory_id, archived = milvus_store._row_entities(hit)
    assert memory_id == "fallback-memory"
    assert archived is False


def test_milvus_collection_initialization_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_milvus(monkeypatch)
    store = MilvusVectorStore("https://localhost:19530/cellin_vectors")
    backend = store._backend
    backend._ensure_collection_exists()


def test_milvus_search_remote_ignores_non_sequence_hit_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    milvus_store._BACKENDS.clear()
    _install_milvus(monkeypatch)
    store = MilvusVectorStore("https://localhost:19530/cellin_vectors")

    class _Collection:
        def search(self, **_: object) -> list[object]:
            return [1]

    def _collection() -> _Collection:
        return _Collection()

    store._backend._collection = _collection  # type: ignore[method-assign]
    assert store._backend._search_remote((0.0,) * 12, limit=10) == []


def test_milvus_search_falls_back_to_local_when_remote_search_raises_type_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    milvus_store._BACKENDS.clear()
    _install_milvus(monkeypatch)
    store = MilvusVectorStore("https://localhost:19530/cellin_vectors")
    store.upsert("memory-1", "atlas architecture")

    def search_raises_type_error(**_: object) -> list[list[object]]:
        raise TypeError("unsupported arg signature")

    def collection() -> Any:
        return type(
            "Collection",
            (),
            {"search": staticmethod(search_raises_type_error)},
        )()

    store._backend._collection = collection  # type: ignore[method-assign]
    assert tuple(item.memory_id for item in store.search("query", limit=10)) == ("memory-1",)


def test_milvus_search_respects_zero_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_milvus(monkeypatch)
    store = MilvusVectorStore("https://localhost:19530/cellin_vectors")
    assert store.search("query", limit=0) == ()


def test_milvus_search_uses_empty_remote_results_on_general_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    milvus_store._BACKENDS.clear()
    _install_milvus(monkeypatch)
    store = MilvusVectorStore("https://localhost:19530/cellin_vectors")
    store.upsert("memory-1", "atlas architecture")

    def search_raises_general_failure(**_: object) -> list[list[object]]:
        raise RuntimeError("milvus down")

    def collection() -> Any:
        return type(
            "Collection",
            (),
            {"search": staticmethod(search_raises_general_failure)},
        )()

    store._backend._collection = collection  # type: ignore[method-assign]
    assert tuple(item.memory_id for item in store.search("query", limit=10)) == ("memory-1",)


def _install_redis_vector(monkeypatch: pytest.MonkeyPatch) -> None:
    state: dict[str, object] = {}

    class _RedisClient:
        def set(self, key: object, value: object, nx: bool = False) -> None | str:
            str_key = str(key)
            if nx and str_key in state:
                return None
            state[str_key] = value
            return "OK"

        def get(self, key: object) -> object | None:
            return state.get(str(key))

        def scan_iter(self, match: str) -> list[str]:
            pattern = match.replace("*", "")
            return [key for key in state if str(key).startswith(pattern)]

    class _RedisLib:
        @classmethod
        def from_url(cls, url: str, decode_responses: bool = True) -> _RedisClient:
            del decode_responses
            state["__url"] = url
            return _RedisClient()

    redis_module = ModuleType("redis")
    redis_module.Redis = _RedisLib
    monkeypatch.setitem(sys.modules, "redis", redis_module)


def test_redis_vector_store_reuses_collection_state_and_filters_archived_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_redis_vector(monkeypatch)

    store = RedisVectorStore("redis://localhost:6379/0?collection=cellin_vectors")
    mirror = RedisVectorStore("redis://localhost:6379/0?collection=cellin_vectors")
    assert store._backend is mirror._backend

    store.upsert("memory-1", "atlas architecture")
    store.upsert("memory-2", "gardening")
    store.delete("memory-2")

    memory_ids = tuple(item.memory_id for item in store.search("query", limit=10))
    assert "memory-1" in memory_ids
    assert "memory-2" not in memory_ids


def test_redis_backend_normalization_default_collection_and_zero_limit() -> None:
    namespace, collection = redis_vector_store._parse_namespace("redis://localhost:6379/0")
    assert namespace == "cellin:0"
    assert collection == "cellin_vectors"


def test_redis_vector_store_handles_invalid_payloads_and_missing_vectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_redis_vector(monkeypatch)

    store = RedisVectorStore("redis://localhost:6379/0?collection=cellin_vectors")
    backend = store._backend
    store.upsert("memory-1", "atlas architecture")
    backend._client.set(backend._key("bad-memory"), "{invalid-json}")
    backend._client.set(
        backend._key("empty-vector"),
        json.dumps({"memory_id": "empty-vector", "vector": []}),
    )
    backend._client.set(
        backend._key("archived-memory"),
        json.dumps({"memory_id": "archived-memory", "archived": True, "vector": [0.1]}),
    )

    assert tuple(item.memory_id for item in store.search("query", limit=10)) == ("memory-1",)
    assert store.search("query", limit=0) == ()


def test_redis_vector_store_does_not_remarshal_collection_initialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_redis_vector(monkeypatch)
    store = RedisVectorStore("redis://localhost:6379/0?collection=cellin_vectors")
    store._backend._initialize_collection()
    assert store._backend._initialized is True
