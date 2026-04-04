"""Multimodal ingestion primitives for Cellin."""

from cellin.ingest.adapters import (
    ChatAdapter,
    ImageAdapter,
    JSONAdapter,
    MarkdownAdapter,
    TextAdapter,
)
from cellin.ingest.envelope import ArtifactEnvelope, IngestionBatchResult
from cellin.ingest.pipeline import CanonicalIngestor

__all__ = [
    "ArtifactEnvelope",
    "CanonicalIngestor",
    "ChatAdapter",
    "ImageAdapter",
    "IngestionBatchResult",
    "JSONAdapter",
    "MarkdownAdapter",
    "TextAdapter",
]
