from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RealtimeCapabilities(BaseModel):
    text: bool = True
    voice: bool = True
    video: bool = True
    human_handoff: bool = True
    autonomous_diagnosis: bool = False
    autonomous_prescribing: bool = False
    autonomous_clinical_writes: bool = False
    appointment_mutations_require_confirmation: bool = True


class ConsentRequirement(BaseModel):
    consent_type: Literal["ai", "audio", "video", "recording"]
    required: bool


class FoundationStatus(BaseModel):
    phase: Literal["AI-0"] = "AI-0"
    enabled: bool = False
    policy_version: str = "patient-agent-safety-v1"
    capabilities: RealtimeCapabilities = Field(default_factory=RealtimeCapabilities)
    consent: list[ConsentRequirement] = Field(
        default_factory=lambda: [
            ConsentRequirement(consent_type="ai", required=True),
            ConsentRequirement(consent_type="audio", required=True),
            ConsentRequirement(consent_type="video", required=True),
            ConsentRequirement(consent_type="recording", required=False),
        ]
    )
