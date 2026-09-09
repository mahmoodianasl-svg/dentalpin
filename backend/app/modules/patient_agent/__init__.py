"""Patient-facing realtime AI agent module.

The module is opt-in (``auto_install=False``) and owns patient-agent session,
consent, audit, reviewed knowledge, guarded appointment, human-handoff, and
visual-snapshot authorization boundaries. It consumes DentalPin capabilities
through explicit contracts and MUST NOT diagnose, prescribe, approve treatment,
or commit clinical records autonomously.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.plugins import BaseModule

from .dental_knowledge_review_router import review_router
from .handoff_staff_router import handoff_staff_router
from .models import (
    PatientAgentAuditEvent,
    PatientAgentConsent,
    PatientAgentDentalKnowledge,
    PatientAgentSession,
    PatientPortalAccount,
)
from .patient_portal_router import portal_router
from .router import router


class PatientAgentModule(BaseModule):
    manifest = {
        "name": "patient_agent",
        "version": "0.1.0",
        "summary": "Realtime patient AI foundation for text, voice, video and safe handoff.",
        "author": "DentalPin Core Team",
        "license": "BSL-1.1",
        "category": "official",
        "depends": ["agenda", "schedules", "patients"],
        "installable": True,
        "auto_install": False,
        "removable": True,
        "role_permissions": {
            "admin": ["*"],
            "dentist": [
                "session.read",
                "audit.read",
                "handoff.accept",
                "knowledge.read",
                "knowledge.review",
            ],
            "receptionist": ["session.read", "handoff.accept"],
        },
        "frontend": {
            "layer_path": "frontend",
            "navigation": [
                {
                    "label": "nav.dentalKnowledge",
                    "icon": "i-lucide-book-open-check",
                    "to": "/ai/dental-knowledge",
                    "permission": "patient_agent.knowledge.read",
                    "order": 80,
                },
            ],
        },
    }

    def get_models(self) -> list:
        return [
            PatientPortalAccount,
            PatientAgentSession,
            PatientAgentConsent,
            PatientAgentAuditEvent,
            PatientAgentDentalKnowledge,
        ]

    def get_router(self) -> APIRouter:
        combined = APIRouter()
        combined.include_router(router)
        combined.include_router(portal_router)
        combined.include_router(review_router)
        combined.include_router(handoff_staff_router)
        return combined

    def get_permissions(self) -> list[str]:
        return [
            "session.read",
            "audit.read",
            "handoff.accept",
            "configure",
            "knowledge.read",
            "knowledge.review",
        ]

    def get_tools(self) -> list:
        return []
