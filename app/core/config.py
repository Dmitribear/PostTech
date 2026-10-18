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
    openai_model: str = "gpt-6-luna"
    jana_model_timeout_seconds: float = Field(default=20, ge=1, le=60)
    # HTTP inference uses a local, read-only language model. No cloud fallback.
    jana_reader_url: str = "http://127.0.0.1:8081"
    # Explicit Compose opt-in, limited to http://jana-reader:8081.
    jana_reader_allow_docker_host: bool = False
    jana_reader_model: str = "jana-reader"
    jana_reader_timeout_seconds: float = Field(default=180, ge=5, le=300)
    # Historical FAQ experiments only; the live agent does not load FAQ examples.
    jana_model_dir: Path = Path(__file__).resolve().parents[2] / ".models/mpnet"
    jana_faq_path: Path = Path(__file__).resolve().parents[2] / "knowledge_base/faq.json"
    jana_min_score: float = Field(default=0.72, ge=0, le=1)
    jana_score_margin: float = Field(default=0.045, ge=0, le=1)
    resend_api_key: SecretStr | None = None
    invitation_email_from: str = "PostTech <onboarding@resend.dev>"
    portal_public_url: AnyHttpUrl | None = None
    telegram_bot_token: SecretStr | None = None
    telegram_bot_username: str = ""
    telegram_worker_secret: SecretStr | None = None
    telegram_api_url: str = "http://api:8000"

    @field_validator("portal_public_url", mode="before")
    @classmethod
    def empty_portal_url(cls, value):
        return value or None


@lru_cache

def get_settings() -> Settings:
    return Settings()
