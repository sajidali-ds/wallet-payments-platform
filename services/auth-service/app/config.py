import re
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PLACEHOLDER = re.compile(r"change[-_]me", re.IGNORECASE)


def _reject_placeholder(name: str, value: str) -> None:
    if _PLACEHOLDER.search(value):
        raise ValueError(f"{name} still has the .env.example placeholder: set a real value")


class Settings(BaseSettings):
    """Every setting comes from an environment variable (DATABASE_URL -> database_url)."""

    model_config = SettingsConfigDict(extra="ignore")

    service_name: str = "auth-service"
    log_level: str = "INFO"
    database_url: str
    jwt_secret: SecretStr  # SecretStr so it never shows up in logs or repr()
    jwt_algorithm: Literal["HS256"] = "HS256"  # fixed list: no surprise algorithms via config
    jwt_expire_minutes: int = Field(default=30, ge=1)
    bcrypt_rounds: int = Field(default=12, ge=4, le=15)

    @field_validator("jwt_secret")
    @classmethod
    def jwt_secret_is_long_enough(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        if len(secret) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")
        _reject_placeholder("JWT_SECRET", secret)
        return value

    @field_validator("database_url")
    @classmethod
    def urls_have_no_placeholder_password(cls, value: str, info: ValidationInfo) -> str:
        _reject_placeholder((info.field_name or "url").upper(), value)
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
