from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.schemas.common import AppRole


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    password: SecretStr = Field(min_length=8, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: SecretStr = Field(min_length=1)


class InvitationCode(BaseModel):
    invitation_code: str = Field(min_length=8, max_length=200)

    @field_validator("invitation_code")
    @classmethod
    def clean_code(cls, value: str) -> str:
        return value.strip()


class RegistrationRequest(InvitationCode):
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    password: SecretStr = Field(min_length=8, max_length=128)

    @field_validator("first_name", "last_name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value or any(ord(char) < 32 for char in value):
            raise ValueError("Enter a valid name")
        return value

    @field_validator("password")
    @classmethod
    def strong_password(cls, value: SecretStr) -> SecretStr:
        password = value.get_secret_value()
        if not any(char.isupper() for char in password) or not any(char.isdigit() for char in password):
            raise ValueError("Password must contain an uppercase letter and a number")
        return value


class VerifyRegistrationRequest(InvitationCode):
    # Supabase projects use six or eight digit email confirmation codes.
    token: str = Field(pattern=r"^(?:[0-9]{6}|[0-9]{8})$")


class CompleteInvitationRequest(InvitationCode, Credentials):
    first_name: str | None = Field(default=None, min_length=1, max_length=80)
    last_name: str | None = Field(default=None, min_length=1, max_length=80)

    @field_validator("first_name", "last_name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        return RegistrationRequest.clean_name(value) if value is not None else None


class PasswordResetRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


class ConfirmPasswordResetRequest(PasswordResetRequest):
    token: str = Field(pattern=r"^(?:[0-9]{6}|[0-9]{8})$")
    password: SecretStr = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def strong_password(cls, value: SecretStr) -> SecretStr:
        return RegistrationRequest.strong_password(value)


class IssueInvitationRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    employee_code: str = Field(min_length=1, max_length=80)
    company: str = Field(min_length=1, max_length=120)
    job_title: str = Field(min_length=1, max_length=160)
    department: str = Field(min_length=1, max_length=160)
    hired_at: date
    manager_id: UUID | None = None
    role: AppRole = "worker"
    vacation_days_remaining: float = Field(default=0, ge=0, le=9999.9, allow_inf_nan=False)
    expires_in_hours: int = Field(default=72, ge=1, le=168)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()

    @field_validator("employee_code", "company", "job_title", "department")
    @classmethod
    def nonblank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Value cannot be blank")
        return value
