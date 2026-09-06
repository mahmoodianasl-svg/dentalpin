"""OpenAI Realtime provider using server-minted ephemeral client secrets."""

from __future__ import annotations

import hashlib
import os

import httpx

from app.modules.patient_agent.providers.base import (
    RealtimeAIProvider,
    RealtimeSessionDescriptor,
    RealtimeSessionRequest,
)


PATIENT_KNOWLEDGE_TOOL = {
    "type": "function",
    "name": "search_patient_dental_knowledge",
    "description": (
        "Search DentalPin's clinic-approved patient education knowledge. Use this for dental "
        "education questions before answering from general knowledge. This tool is read-only "
        "and must not be used to diagnose, prescribe, approve treatment, or alter records."
    ),
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "query": {
                "type": "string",
                "description": "The patient's dental education question or search phrase.",
            },
            "topic": {
                "type": ["string", "null"],
                "description": "Optional DentalPin dental topic filter.",
            },
        },
        "required": ["query"],
    },
}


class OpenAIRealtimeProvider(RealtimeAIProvider):
    name = "openai"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model or os.getenv("PATIENT_AGENT_REALTIME_MODEL", "gpt-realtime-2.1")

    async def create_session(self, request: RealtimeSessionRequest) -> RealtimeSessionDescriptor:
        if not self.api_key:
            raise RuntimeError("Realtime AI provider is not configured")

        safety_id = hashlib.sha256(request.session_id.encode("utf-8")).hexdigest()
        payload = {
            "session": {
                "type": "realtime",
                "model": self.model,
                "modalities": list(request.modalities),
                "instructions": (
                    "You are DentalPin's patient assistant. Never diagnose, prescribe, "
                    "or claim to replace a dentist. For dental education questions, call "
                    "search_patient_dental_knowledge and ground the answer in the returned "
                    "clinic-approved sources. If the tool returns fallback_required=true, say "
                    "that approved clinic guidance was not found and recommend appropriate "
                    "human follow-up rather than inventing clinical advice. Use DentalPin tools "
                    "for patient-specific facts and escalate urgent or clinical decisions to a "
                    "human professional."
                ),
                "tools": [PATIENT_KNOWLEDGE_TOOL],
                "tool_choice": "auto",
                "audio": {"output": {"voice": "marin"}},
            }
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "OpenAI-Safety-Identifier": safety_id,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/realtime/client_secrets",
                headers=headers,
                json=payload,
            )
        response.raise_for_status()
        data = response.json()
        secret = data.get("value") or data.get("client_secret", {}).get("value")
        if not secret:
            raise RuntimeError("Realtime provider returned no ephemeral client secret")
        expires_at = data.get("expires_at") or data.get("client_secret", {}).get("expires_at")
        provider_ref = str(data.get("id") or request.session_id)
        return RealtimeSessionDescriptor(
            provider=self.name,
            provider_session_ref=provider_ref,
            client_secret=str(secret),
            expires_at_epoch=int(expires_at) if expires_at is not None else None,
        )

    async def close_session(self, provider_session_ref: str) -> None:
        # Ephemeral WebRTC secrets expire quickly; provider-side explicit close is
        # not required for the AI-1 token-minting flow. DentalPin still closes and
        # audits its own session state.
        return None
