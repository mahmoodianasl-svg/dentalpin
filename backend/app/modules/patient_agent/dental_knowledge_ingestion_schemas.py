from __future__ import annotations

from pydantic import BaseModel, Field

from .dental_conversation import DentalTopic
from .dental_knowledge_review_schemas import DentalKnowledgeReviewResponse


class DentalKnowledgeCorpusEntry(BaseModel):
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


class DentalKnowledgeCorpusImportRequest(BaseModel):
    corpus_id: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
    corpus_version: str = Field(min_length=1, max_length=80)
    entries: list[DentalKnowledgeCorpusEntry] = Field(min_length=1, max_length=100)


class DentalKnowledgeCorpusImportResponse(BaseModel):
    corpus_id: str
    corpus_version: str
    created_count: int
    skipped_count: int
    records: list[DentalKnowledgeReviewResponse]
