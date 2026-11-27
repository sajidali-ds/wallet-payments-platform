import re
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# .env.example ships values such as "change_me_pg_password". Starting with one of them would mean
# running with a password that is public in the repository, so the service refuses to start.
_PLACEHOLDER = re.compile(r"change[-_]me", re.IGNORECASE)


def _reject_placeholder(name: str, value: str) -> None:
    if _PLACEHOLDER.search(value):
        raise ValueError(f"{name} still has the .env.example placeholder: set a real value")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    service_name: str = "notification-service"
    log_level: str = "INFO"
    database_url: str
    jwt_secret: SecretStr
    jwt_algorithm: Literal["HS256"] = "HS256"

    rabbitmq_url: str
    exchange_name: str = "wallet.events"
    queue_name: str = "notifications.transfer_completed"
    prefetch_count: int = Field(default=10, ge=1)  # unacked messages the broker lets us hold
    max_retries: int = Field(default=3, ge=0, le=10)
    # Retry n waits base * 2**(n-1): 5s, 10s, 20s with the defaults.
    retry_base_delay_ms: int = Field(default=5000, ge=1)

    @field_validator("jwt_secret")
    @classmethod
    def jwt_secret_is_long_enough(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        if len(secret) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")
        _reject_placeholder("JWT_SECRET", secret)
        return value

    @field_validator("database_url", "rabbitmq_url")
    @classmethod
    def urls_have_no_placeholder_password(cls, value: str, info: ValidationInfo) -> str:
        _reject_placeholder((info.field_name or "url").upper(), value)
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
