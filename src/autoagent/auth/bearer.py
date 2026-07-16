from __future__ import annotations

import hmac
from dataclasses import dataclass

import jwt

from autoagent.auth.jwt import decode_token
from autoagent.config.settings import get_settings


@dataclass(frozen=True)
class BearerAuthError(Exception):
    reason: str


def resolve_bearer_subject(token: str) -> str:
    settings = get_settings()
    static_api_key = settings.static_api_key
    if static_api_key and hmac.compare_digest(token, static_api_key.get_secret_value()):
        return settings.admin_username

    try:
        payload = decode_token(token)
    except jwt.PyJWTError as exc:
        raise BearerAuthError("invalid") from exc

    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise BearerAuthError("malformed")
    return subject
