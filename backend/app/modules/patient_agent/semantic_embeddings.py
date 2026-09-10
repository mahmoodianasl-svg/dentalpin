"""Embedding primitives for patient-agent dental knowledge retrieval.

The patient-agent retrieval layer treats embeddings as an optional ranking
signal. Clinical eligibility remains governed exclusively by the existing
clinic/review/locale/topic filters, and callers must retain a safe fallback
when an embedding provider is unavailable.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Protocol

from app.config import settings

SEMANTIC_EMBEDDING_KEY = "semantic_embedding"


class EmbeddingProvider(Protocol):
    """Minimal async embedding contract used by the patient-agent RAG path."""

    @property
    def model(self) -> str: ...

    async def embed(self, text: str) -> Sequence[float]: ...


class OpenAIEmbeddingProvider:
    """OpenAI embedding provider using DentalPin's existing OpenAI dependency."""

    def __init__(self, *, api_key: str, model: str) -> None:
        if not api_key.strip():
            raise ValueError("OpenAI embedding provider requires an API key")
        if not model.strip():
            raise ValueError("OpenAI embedding provider requires a model")

        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    async def embed(self, text: str) -> Sequence[float]:
        normalized = text.strip()
        if not normalized:
            return ()
        response = await self._client.embeddings.create(model=self._model, input=normalized)
        if not response.data:
            return ()
        return tuple(float(value) for value in response.data[0].embedding)


def configured_embedding_provider() -> EmbeddingProvider | None:
    """Return the configured provider, or ``None`` for deterministic fallback."""

    if not settings.OPENAI_API_KEY.strip():
        return None
    return OpenAIEmbeddingProvider(
        api_key=settings.OPENAI_API_KEY,
        model=settings.PATIENT_AGENT_EMBEDDING_MODEL,
    )


def semantic_embedding_input(*, title: str, content: str) -> str:
    """Build the stable text representation used for both indexing and validation."""

    return f"{title.strip()}\n\n{content.strip()}".strip()


def semantic_content_fingerprint(*, title: str, content: str) -> str:
    """Fingerprint the exact text represented by a stored semantic vector."""

    payload = semantic_embedding_input(title=title, content=content).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def with_semantic_embedding(
    metadata: Mapping[str, object] | None,
    *,
    model: str,
    vector: Sequence[float],
    title: str,
    content: str,
) -> dict[str, object]:
    """Return copied metadata with a validated, content-bound semantic vector."""

    normalized = tuple(float(value) for value in vector)
    if not normalized or any(not math.isfinite(value) for value in normalized):
        raise ValueError("Semantic embedding vector must contain finite values")
    if not model.strip():
        raise ValueError("Semantic embedding model is required")

    updated = dict(metadata or {})
    updated[SEMANTIC_EMBEDDING_KEY] = {
        "model": model,
        "dimensions": len(normalized),
        "vector": list(normalized),
        "content_sha256": semantic_content_fingerprint(title=title, content=content),
        "indexed_at": datetime.now(UTC).isoformat(),
    }
    return updated


def without_semantic_embedding(metadata: Mapping[str, object] | None) -> dict[str, object]:
    """Return copied metadata with any semantic index payload removed."""

    updated = dict(metadata or {})
    updated.pop(SEMANTIC_EMBEDDING_KEY, None)
    return updated


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float | None:
    """Return cosine similarity for equal non-empty finite vectors.

    Invalid, dimension-mismatched, non-finite, or zero-norm vectors return
    ``None`` so retrieval can fall back without treating malformed metadata as
    a relevant semantic match.
    """

    if not left or not right or len(left) != len(right):
        return None
    if any(not math.isfinite(value) for value in (*left, *right)):
        return None
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return None
    return dot / (left_norm * right_norm)
