from functools import lru_cache

from pydantic import AnyHttpUrl, SecretStr, field_validator
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

    @field_validator("portal_public_url", mode="before")
    @classmethod
    def empty_portal_url(cls, value):
        return value or None


@lru_cache

def get_settings() -> Settings:
    return Settings()
