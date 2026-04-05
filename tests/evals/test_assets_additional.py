"""Additional eval asset validation coverage."""

from __future__ import annotations

import pytest

from cellin.evals import assets


@pytest.mark.parametrize(
    ("payload", "match"),
    (
        ([123], "memory corpus\\[0\\] must be a JSON object"),
        (
            [
                {
                    "observed_at": "2026-04-01T10:00:00+00:00",
                    "text": "Atlas note",
                    "metadata": {},
                    "salience_score": 0.5,
                    "trust_score": 0.8,
                }
            ],
            "missing required field 'memory_id'",
        ),
        (
            [
                {
                    "memory_id": "bool-number",
                    "observed_at": "2026-04-01T10:00:00+00:00",
                    "text": "Atlas note",
                    "metadata": {},
                    "salience_score": True,
                    "trust_score": 0.8,
                }
            ],
            "salience_score has invalid type bool",
        ),
        (
            [
                {
                    "memory_id": "bad-access-count",
                    "observed_at": "2026-04-01T10:00:00+00:00",
                    "text": "Atlas note",
                    "metadata": {},
                    "salience_score": 0.5,
                    "trust_score": 0.8,
                    "access_count": True,
                }
            ],
            "access_count has invalid type bool",
        ),
        (
            [
                {
                    "memory_id": "bad-datetime",
                    "observed_at": "not-a-datetime",
                    "text": "Atlas note",
                    "metadata": {},
                    "salience_score": 0.5,
                    "trust_score": 0.8,
                }
            ],
            "must be an ISO-8601 datetime string",
        ),
    ),
)
def test_load_memory_atoms_rejects_invalid_rows(payload: object, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        assets._load_memory_atoms(payload, context="memory corpus")


@pytest.mark.parametrize(
    ("payload", "match"),
    (
        ([123], "envelope corpus\\[0\\] must be a JSON object"),
        (
            [
                {
                    "envelope_id": "bad-envelope",
                    "modality": "text",
                    "payload": "payload",
                    "source_id": "source",
                    "source_type": "fixture",
                    "observed_at": "not-a-datetime",
                    "metadata": {},
                }
            ],
            "must be an ISO-8601 datetime string",
        ),
        (
            [
                {
                    "envelope_id": "bad-envelope",
                    "modality": "unknown",
                    "payload": "payload",
                    "source_id": "source",
                    "source_type": "fixture",
                    "observed_at": "2026-04-01T10:00:00+00:00",
                    "metadata": {},
                }
            ],
            "unknown value 'unknown'",
        ),
    ),
)
def test_load_envelopes_reject_invalid_rows(payload: object, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        assets._load_envelopes(payload, context="envelope corpus")
