from typing import Any

import jwt

from app.config import Settings


def decode_access_token(token: str, settings: Settings) -> dict[str, Any]:
    """Verifies signature and expiry locally. Raises jwt.ExpiredSignatureError / InvalidTokenError.

    `algorithms` is passed explicitly so a forged token claiming alg "none" is rejected.
    """
    return jwt.decode(
        token,
        settings.jwt_secret.get_secret_value(),
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "iat", "sub"]},
    )
