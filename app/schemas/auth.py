from pydantic import BaseModel, Field, SecretStr


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    password: SecretStr = Field(min_length=8, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: SecretStr = Field(min_length=1)
