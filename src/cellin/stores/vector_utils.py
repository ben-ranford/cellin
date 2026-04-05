"""Shared deterministic vector helpers for first-party vector backends."""

from __future__ import annotations

import hashlib
import math
import re

TOKEN_RE = re.compile(r"[a-z0-9]+")
VECTOR_SIZE = 12


def _tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def vectorize(text: str) -> tuple[float, ...]:
    buckets = [0.0] * VECTOR_SIZE
    for token in _tokenize(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket_index = int.from_bytes(digest[:4], byteorder="big") % VECTOR_SIZE
        buckets[bucket_index] += 1.0

    norm = math.sqrt(sum(value * value for value in buckets))
    if norm == 0:
        return tuple(buckets)

    return tuple(value / norm for value in buckets)


def cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if not left or not right:
        return 0.0

    return sum(a * b for a, b in zip(left, right, strict=True))
