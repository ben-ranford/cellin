"""First-party modality adapters for Cellin ingestion."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from cellin.core import Artifact, Modality, Provenance
from cellin.core.models import JSONValue
from cellin.ingest.envelope import ArtifactEnvelope


def _artifact(
    envelope: ArtifactEnvelope,
    *,
    content: str,
    metadata: Mapping[str, JSONValue] | None = None,
) -> Artifact:
    return Artifact(
        artifact_id=envelope.envelope_id,
        modality=envelope.modality,
        content=content,
        provenance=Provenance(
            source_id=envelope.source_id,
            source_type=envelope.source_type,
            ingest_run_id=f"ingest:{envelope.envelope_id}",
        ),
        created_at=envelope.observed_at,
        observed_at=envelope.observed_at,
        metadata={**envelope.metadata, **(metadata or {})},
    )


@dataclass(slots=True)
class TextAdapter:
    """Normalizes plain text envelopes."""

    def supports(self, modality: Modality) -> bool:
        return modality is Modality.TEXT

    def normalize(self, envelope: ArtifactEnvelope) -> Artifact:
        assert isinstance(envelope.payload, str)
        return _artifact(envelope, content=envelope.payload)


@dataclass(slots=True)
class MarkdownAdapter:
    """Normalizes markdown envelopes."""

    def supports(self, modality: Modality) -> bool:
        return modality is Modality.MARKDOWN

    def normalize(self, envelope: ArtifactEnvelope) -> Artifact:
        assert isinstance(envelope.payload, str)
        return _artifact(envelope, content=envelope.payload)


@dataclass(slots=True)
class JSONAdapter:
    """Normalizes structured JSON envelopes."""

    def supports(self, modality: Modality) -> bool:
        return modality is Modality.JSON

    def normalize(self, envelope: ArtifactEnvelope) -> Artifact:
        assert isinstance(envelope.payload, dict | list)
        return _artifact(
            envelope,
            content=json.dumps(envelope.payload, sort_keys=True),
        )


@dataclass(slots=True)
class ChatAdapter:
    """Normalizes conversational payloads into one artifact."""

    def supports(self, modality: Modality) -> bool:
        return modality is Modality.CHAT

    def normalize(self, envelope: ArtifactEnvelope) -> Artifact:
        assert isinstance(envelope.payload, dict)
        messages = envelope.payload.get("messages", [])
        assert isinstance(messages, list)
        rendered_messages: list[str] = []
        for message in messages:
            assert isinstance(message, dict)
            role = str(message.get("role", "unknown"))
            content = str(message.get("content", ""))
            rendered_messages.append(f"{role}: {content}")
        metadata = {"conversation_id": envelope.payload.get("conversation_id")}
        return _artifact(envelope, content="\n".join(rendered_messages), metadata=metadata)


@dataclass(slots=True)
class ImageAdapter:
    """Normalizes image payloads with local fallback OCR/caption behavior."""

    text_provider: Callable[[ArtifactEnvelope], str] | None = None

    def supports(self, modality: Modality) -> bool:
        return modality is Modality.IMAGE

    def normalize(self, envelope: ArtifactEnvelope) -> Artifact:
        assert isinstance(envelope.payload, dict)

        if self.text_provider is not None:
            content = self.text_provider(envelope)
        else:
            caption = envelope.payload.get("caption")
            ocr_text = envelope.payload.get("ocr_text") or envelope.metadata.get("ocr_text")
            path = envelope.payload.get("path", "unknown-image")
            parts = [
                str(value)
                for value in (caption, ocr_text, f"Image asset: {path}")
                if value is not None
            ]
            content = " | ".join(parts)

        return _artifact(
            envelope,
            content=content,
            metadata={"image_path": envelope.payload.get("path")},
        )


class EnvelopeAdapter(Protocol):
    """A modality adapter that accepts the canonical artifact envelope."""

    def supports(self, modality: Modality) -> bool:
        """Whether the adapter supports a given modality."""

    def normalize(self, envelope: ArtifactEnvelope) -> Artifact:
        """Normalize one artifact envelope."""


def built_in_adapters(
    *,
    image_text_provider: Callable[[ArtifactEnvelope], str] | None = None,
) -> tuple[EnvelopeAdapter, ...]:
    """Return the first-party adapter set."""

    return (
        TextAdapter(),
        MarkdownAdapter(),
        ChatAdapter(),
        JSONAdapter(),
        ImageAdapter(text_provider=image_text_provider),
    )
