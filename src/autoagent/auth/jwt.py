from datetime import datetime, timedelta, timezone

import jwt

from autoagent.config.settings import get_settings

ALG = "HS256"


def _secret() -> str:
    return get_settings().jwt_secret


def _expiry_hours() -> int:
    return get_settings().jwt_expires_hours


def create_access_token(username: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=_expiry_hours())).timestamp()),
    }
    return jwt.encode(payload, _secret(), algorithm=ALG)


def decode_token(token: str) -> dict:
    return jwt.decode(token, _secret(), algorithms=[ALG])
