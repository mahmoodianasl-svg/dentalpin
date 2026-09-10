"""Embedding primitives for patient-agent dental knowledge retrieval.

The patient-agent retrieval layer treats embeddings as an optional ranking
signal. Clinical eligibility remains governed exclusively by the existing
clinic/review/locale/topic filters, and callers must retain a safe fallback
when an embedding provider is unavailable.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Protocol

from app.config import settings


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


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float | None:
    """Return cosine similarity for equal non-empty vectors.

    Invalid, zero-length, dimension-mismatched, or zero-norm vectors return
    ``None`` so retrieval can fall back without treating malformed metadata as
    a relevant semantic match.
    """

    if not left or not right or len(left) != len(right):
        return None
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return None
    return dot / (left_norm * right_norm)
