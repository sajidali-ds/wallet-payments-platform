import pytest
from pydantic import ValidationError

from app.schemas.auth import LoginRequest, RegisterRequest


def test_register_accepts_valid_input_and_lowercases_email():
    body = RegisterRequest(email="Alice@Example.COM", password="correct-horse")
    assert body.email == "alice@example.com"


@pytest.mark.parametrize(
    "password",
    [
        "short",  # under 8 characters
        "a" * 73,  # over 72 characters
        "é" * 40,  # only 40 characters but 80 bytes: bcrypt would silently truncate
    ],
)
def test_register_rejects_bad_passwords(password):
    with pytest.raises(ValidationError):
        RegisterRequest(email="a@example.com", password=password)


def test_register_rejects_invalid_email():
    with pytest.raises(ValidationError):
        RegisterRequest(email="not-an-email", password="correct-horse")


def test_register_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        RegisterRequest(email="a@example.com", password="correct-horse", role="admin")


def test_login_requires_a_password():
    with pytest.raises(ValidationError):
        LoginRequest(email="a@example.com", password="")
