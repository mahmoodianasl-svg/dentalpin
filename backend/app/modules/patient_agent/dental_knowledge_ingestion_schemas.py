from __future__ import annotations

import json
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .dental_conversation import DentalTopic
from .dental_knowledge_review_schemas import DentalKnowledgeReviewResponse


class DentalKnowledgeCorpusEntry(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    entry_key: str = Field(
        min_length=1,
        max_length=120,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    )
    topic: DentalTopic
    locale: str = Field(default="en", min_length=2, max_length=20, pattern=r"^[A-Za-z0-9-]+$")
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=100_000)
    source_name: str = Field(min_length=1, max_length=255)
    source_reference: str = Field(min_length=1, max_length=4000)
    source_metadata: dict[str, object] = Field(default_factory=dict)

    @field_validator("source_reference")
    @classmethod
    def validate_source_reference(cls, value: str) -> str:
        parsed = urlsplit(value)
        if any(character.isspace() for character in value):
            raise ValueError("source_reference must not contain whitespace")
        try:
            parsed.port
        except ValueError as exc:
            raise ValueError("source_reference contains an invalid port") from exc
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            raise ValueError("source_reference must be an absolute HTTPS URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("source_reference must not contain credentials")
        return value

    @field_validator("source_metadata")
    @classmethod
    def validate_source_metadata(cls, value: dict[str, object]) -> dict[str, object]:
        try:
            canonical = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("source_metadata must contain only finite JSON values") from exc
        if len(canonical.encode("utf-8")) > 32_768:
            raise ValueError("source_metadata must not exceed 32768 UTF-8 bytes")
        return value


class DentalKnowledgeCorpusImportRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    corpus_id: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
    corpus_version: str = Field(min_length=1, max_length=80)
    entries: list[DentalKnowledgeCorpusEntry] = Field(min_length=1, max_length=100)


class DentalKnowledgeCorpusImportResponse(BaseModel):
    corpus_id: str
    corpus_version: str
    created_count: int
    skipped_count: int
    records: list[DentalKnowledgeReviewResponse]
