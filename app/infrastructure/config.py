from functools import lru_cache
from pathlib import Path

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=False,
    )

    supabase_url: AnyHttpUrl | str | None = None
    supabase_key: SecretStr | str | None = None
    supabase_anon_key: SecretStr | str | None = None
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o-mini"
    resend_api_key: SecretStr | None = None
    invitation_email_from: str = "PostTech <onboarding@resend.dev>"
    portal_public_url: AnyHttpUrl | None = None
    jana_model_timeout_seconds: float = Field(default=20, ge=1, le=60)
    jana_reader_url: str = "http://127.0.0.1:8081"
    jana_reader_model: str = "jana-reader"
    jana_reader_timeout_seconds: float = Field(default=120, ge=5, le=300)
    jana_model_dir: Path = Path(__file__).resolve().parents[2] / ".models/mpnet"
    jana_faq_path: Path = (
        Path(__file__).resolve().parents[2] / "knowledge_base/faq.json"
    )
    jana_min_score: float = Field(default=0.72, ge=0, le=1)
    jana_score_margin: float = Field(default=0.045, ge=0, le=1)

    @field_validator("portal_public_url", mode="before")
    @classmethod
    def empty_portal_url(cls, value):
        return value or None


@lru_cache
def get_settings() -> Settings:
    return Settings()
