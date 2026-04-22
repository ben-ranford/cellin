"""Multimodal ingestion primitives for Cellin."""

from cellin.ingest.adapters import (
    AudioAdapter,
    ChatAdapter,
    ImageAdapter,
    JSONAdapter,
    MarkdownAdapter,
    TextAdapter,
    UnsupportedModalityError,
    VideoAdapter,
)
from cellin.ingest.envelope import ArtifactEnvelope, IngestionBatchResult
from cellin.ingest.pipeline import CanonicalIngestor

__all__ = [
    "ArtifactEnvelope",
    "AudioAdapter",
    "CanonicalIngestor",
    "ChatAdapter",
    "ImageAdapter",
    "IngestionBatchResult",
    "JSONAdapter",
    "MarkdownAdapter",
    "TextAdapter",
    "UnsupportedModalityError",
    "VideoAdapter",
]
