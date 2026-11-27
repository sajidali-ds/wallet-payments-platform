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

    service_name: str = "wallet-service"
    log_level: str = "INFO"
    database_url: str
    # Same secret as auth-service: that is how this service verifies tokens without calling it.
    jwt_secret: SecretStr
    jwt_algorithm: Literal["HS256"] = "HS256"

    redis_url: str
    balance_cache_ttl_seconds: int = Field(default=60, ge=1)
    rate_limit_transfers_per_minute: int = Field(default=20, ge=1)
    rate_limit_reads_per_minute: int = Field(default=120, ge=1)
    fraud_max_transfers_per_window: int = Field(default=5, ge=1)  # "more than 5" gets flagged
    fraud_window_seconds: int = Field(default=60, ge=1)

    rabbitmq_url: str
    exchange_name: str = "wallet.events"
    outbox_enabled: bool = True
    outbox_poll_interval_seconds: float = Field(default=1.0, gt=0)
    outbox_batch_size: int = Field(default=50, ge=1, le=1000)

    @field_validator("jwt_secret")
    @classmethod
    def jwt_secret_is_long_enough(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        if len(secret) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")
        _reject_placeholder("JWT_SECRET", secret)
        return value

    @field_validator("database_url", "rabbitmq_url", "redis_url")
    @classmethod
    def urls_have_no_placeholder_password(cls, value: str, info: ValidationInfo) -> str:
        _reject_placeholder((info.field_name or "url").upper(), value)
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
