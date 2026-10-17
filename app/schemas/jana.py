from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class KnowledgeMetadata(BaseModel):
    version: str | None = None
    freshness: str | None = None
    updated_at: str | None = None
    reviewed_at: str | None = None
    review_due_at: str | None = None


class JanaSource(KnowledgeMetadata):
    id: UUID
    title: str
    url: str = Field(description="Relative API URL; fetch with the user's Bearer token.")
    excerpt: str = Field(description="Verbatim excerpt of the retrieved article.")


class JanaAnswer(BaseModel):
    answer: str
    sources: list[JanaSource]
    grounded: bool = Field(description="Selected verbatim evidence exists in the active knowledge snapshot; not a guarantee of semantic correctness.")
    escalation_suggested: bool
    mode: Literal["generated", "excerpts", "refusal"]


class JanaArticle(KnowledgeMetadata):
    id: UUID
    title: str
    content: str
    source_title: str
    source_url: str | None = None


class JanaError(BaseModel):
    detail: str
