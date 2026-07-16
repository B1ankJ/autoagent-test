from datetime import datetime, timedelta, timezone

import jwt

from autoagent.config.settings import get_settings

ALG = "HS256"
# aud/iss on every token we issue, verified on every token we accept — scopes
# our tokens to this service specifically (defense in depth if jwt_secret
# were ever reused/leaked elsewhere) rather than accepting any HS256 token
# signed with the same secret regardless of what it was minted for.
AUDIENCE = "autoagent-api"
ISSUER = "autoagent"
# Tolerate small clock drift between the issuing and verifying host (only
# matters once this runs as more than a single process on one machine)
# instead of hard-failing a token that's technically still fresh.
LEEWAY_SEC = 30


def _secret() -> str:
    return get_settings().jwt_secret.get_secret_value()


def _expiry_hours() -> int:
    return get_settings().jwt_expires_hours


def create_access_token(username: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=_expiry_hours())).timestamp()),
        "aud": AUDIENCE,
        "iss": ISSUER,
    }
    return jwt.encode(payload, _secret(), algorithm=ALG)


def decode_token(token: str) -> dict:
    return jwt.decode(
        token,
        _secret(),
        algorithms=[ALG],
        audience=AUDIENCE,
        issuer=ISSUER,
        leeway=LEEWAY_SEC,
    )
