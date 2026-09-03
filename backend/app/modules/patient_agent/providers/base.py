from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass(frozen=True)
class RealtimeSessionRequest:
    session_id: str
    channel: str
    locale: str | None
    modalities: tuple[str, ...]


@dataclass(frozen=True)
class RealtimeSessionDescriptor:
    provider: str
    provider_session_ref: str
    client_secret: str | None = None
    expires_at_epoch: int | None = None


class RealtimeAIProvider(ABC):
    """Provider-neutral contract for low-latency text/voice/video sessions.

    Provider credentials remain server-side. Implementations return only
    short-lived session material suitable for the authenticated client.
    """

    name: str

    @abstractmethod
    async def create_session(self, request: RealtimeSessionRequest) -> RealtimeSessionDescriptor:
        raise NotImplementedError

    @abstractmethod
    async def close_session(self, provider_session_ref: str) -> None:
        raise NotImplementedError

    async def stream_server_events(self, provider_session_ref: str) -> AsyncIterator[dict]:
        if False:
            yield {}
        return
