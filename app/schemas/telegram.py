from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TelegramStatus(BaseModel):
    enabled: bool
    linked: bool
    telegram_username: str | None = None
    notifications_enabled: bool = False
    bot_username: str | None = None
    link_id: UUID | None = None


class TelegramLinkResponse(BaseModel):
    url: str
    expires_at: datetime


class TelegramSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notifications_enabled: bool


class ConsumeTelegramLink(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    telegram_user_id: int = Field(gt=0, lt=2**63, strict=True)
    chat_id: int = Field(gt=0, lt=2**63, strict=True)
    username: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_]+$")

    @model_validator(mode="after")
    def private_chat(self):
        if self.chat_id != self.telegram_user_id:
            raise ValueError("Linking is only available in a private chat")
        return self


class TelegramAcknowledgement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lease_token: UUID
    status: Literal["sent", "retry", "blocked"]
    retry_after_seconds: int = Field(default=30, ge=1, le=86400)


class TelegramWorkerState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bot_id: int = Field(gt=0, lt=2**63, strict=True)
    offset: int = Field(ge=0, lt=2**63, strict=True)
