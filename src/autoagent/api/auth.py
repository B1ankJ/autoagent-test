from fastapi import APIRouter, HTTPException, status

from autoagent.auth.jwt import create_access_token
from autoagent.auth.passwords import hash_password, verify_password
from autoagent.config.settings import get_settings
from autoagent.models.api import LoginRequest, LoginResponse
from autoagent.storage.users import get_user

router = APIRouter(prefix="/auth", tags=["auth"])

# Computed once at import time: an unknown-username login runs a real bcrypt
# check against this instead of short-circuiting past verify_password, so an
# attacker can't distinguish "no such user" from "wrong password" by timing
# the response (bcrypt's check cost dwarfs the DB lookup miss otherwise).
_DUMMY_HASH = hash_password("not-a-real-password-timing-decoy")


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest) -> LoginResponse:
    user = await get_user(req.username)
    hashed = user.password_hash if user is not None else _DUMMY_HASH
    password_ok = verify_password(req.password, hashed)
    if user is None or not password_ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token(req.username)
    return LoginResponse(token=token, expires_in_sec=get_settings().jwt_expires_hours * 3600)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout() -> None:
    # Stateless JWT; client simply drops token. Endpoint exists for UX/logging symmetry.
    return None
