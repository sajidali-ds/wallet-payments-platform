import pytest
from pydantic import ValidationError

from app.config import Settings

GOOD = {
    "database_url": "postgresql://wallet:s3cretpassw0rd@postgres:5432/auth_db",
    "jwt_secret": "a-long-random-secret-of-at-least-32-characters",
}


def test_accepts_real_values():
    assert Settings(**GOOD).service_name == "auth-service"


def test_rejects_a_short_jwt_secret():
    with pytest.raises(ValidationError, match="at least 32"):
        Settings(**{**GOOD, "jwt_secret": "too-short"})


@pytest.mark.parametrize("secret", ["change-me-" + "x" * 40, "CHANGE_ME_" + "x" * 40])
def test_rejects_the_placeholder_jwt_secret_from_env_example(secret):
    with pytest.raises(ValidationError, match="placeholder"):
        Settings(**{**GOOD, "jwt_secret": secret})


def test_rejects_the_placeholder_database_password_from_env_example():
    url = "postgresql://wallet:change_me_pg_password@postgres:5432/auth_db"
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(**{**GOOD, "database_url": url})
