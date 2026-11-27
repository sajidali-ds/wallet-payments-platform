import pytest
from pydantic import ValidationError

from app.config import Settings

GOOD = {
    "database_url": "postgresql://wallet:s3cretpassw0rd@postgres:5432/wallet_db",
    "jwt_secret": "a-long-random-secret-of-at-least-32-characters",
    "redis_url": "redis://redis:6379/0",
    "rabbitmq_url": "amqp://wallet:an0therpassw0rd@rabbitmq:5672/",
}


def test_accepts_real_values():
    assert Settings(**GOOD).service_name == "wallet-service"


def test_rejects_a_short_jwt_secret():
    with pytest.raises(ValidationError, match="at least 32"):
        Settings(**{**GOOD, "jwt_secret": "too-short"})


def test_rejects_the_placeholder_jwt_secret_from_env_example():
    with pytest.raises(ValidationError, match="placeholder"):
        Settings(**{**GOOD, "jwt_secret": "change-me-" + "x" * 40})


@pytest.mark.parametrize(
    ("field", "url"),
    [
        ("database_url", "postgresql://wallet:change_me_pg_password@postgres:5432/wallet_db"),
        ("rabbitmq_url", "amqp://wallet:change_me_rabbit_password@rabbitmq:5672/"),
    ],
)
def test_rejects_placeholder_passwords_inside_connection_urls(field, url):
    with pytest.raises(ValidationError, match=field.upper()):
        Settings(**{**GOOD, field: url})


@pytest.mark.parametrize("field", ["rate_limit_transfers_per_minute", "fraud_window_seconds"])
def test_numeric_limits_must_be_positive(field):
    with pytest.raises(ValidationError):
        Settings(**{**GOOD, field: 0})
