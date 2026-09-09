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
            "query": {"type": "string"},
            "topic": {"type": ["string", "null"]},
        },
        "required": ["query"],
    },
}

PATIENT_INTAKE_RISK_TOOL = {
    "type": "function",
    "name": "assess_patient_intake_risk",
    "description": (
        "Submit factual structured intake signals to DentalPin for deterministic safety risk "
        "classification. Use this whenever the patient reports pain, swelling, bleeding, fever "
        "or systemic illness, trauma, breathing difficulty, swallowing difficulty, uncontrolled "
        "bleeding, or facial/neck swelling. DentalPin derives urgency; do not diagnose."
    ),
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "reason": {
                "type": "string",
                "description": "Concise factual summary of what the patient reported.",
            },
            "signals": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": {
                    "type": "string",
                    "enum": [
                        "pain",
                        "swelling",
                        "bleeding",
                        "fever_or_systemic_illness",
                        "trauma",
                        "difficulty_breathing",
                        "difficulty_swallowing",
                        "uncontrolled_bleeding",
                        "facial_or_neck_swelling",
                    ],
                },
            },
        },
        "required": ["reason", "signals"],
    },
}

PATIENT_HANDOFF_TOOL = {
    "type": "function",
    "name": "request_patient_human_handoff",
    "description": (
        "Request a human DentalPin handoff when the patient asks for a person or a clinical "
        "decision is needed. Urgency is not chosen by the model; DentalPin derives it from the "
        "session's structured intake risk assessment."
    ),
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "reason": {
                "type": "string",
                "description": "Concise factual handoff summary without diagnosis.",
            },
        },
        "required": ["reason"],
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
                    "You are DentalPin's patient assistant. Never diagnose, prescribe, or claim "
                    "to replace a dentist. For dental education questions, call "
                    "search_patient_dental_knowledge and ground the answer in clinic-approved "
                    "sources. Whenever the patient reports an intake safety signal such as pain, "
                    "swelling, bleeding, fever/systemic illness, trauma, breathing difficulty, "
                    "swallowing difficulty, uncontrolled bleeding, or facial/neck swelling, call "
                    "assess_patient_intake_risk with only the factual signals and summary. "
                    "DentalPin, not the model, determines urgency. If the risk result requires "
                    "handoff, stop routine scheduling and follow the returned escalation state. "
                    "Use request_patient_human_handoff for direct requests for a person or when a "
                    "clinical decision is needed; do not assign urgency yourself."
                ),
                "tools": [
                    PATIENT_KNOWLEDGE_TOOL,
                    PATIENT_INTAKE_RISK_TOOL,
                    PATIENT_HANDOFF_TOOL,
                ],
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
        return None
