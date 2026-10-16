from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class JanaSource(BaseModel):
    id: UUID
    title: str
    url: str = Field(description="Relative API URL; fetch with the user's Bearer token.")
    excerpt: str = Field(description="Verbatim excerpt of the retrieved article.")


class JanaAnswer(BaseModel):
    answer: str
    sources: list[JanaSource]
    grounded: bool = Field(description="The selected FAQ quote exists in an active source; not a confidence score or a guarantee of relevance.")
    escalation_suggested: bool
    mode: Literal["generated", "excerpts", "refusal"]


class JanaArticle(BaseModel):
    id: UUID
    title: str
    content: str
    source_title: str
    source_url: str | None = None


class JanaError(BaseModel):
    detail: str
