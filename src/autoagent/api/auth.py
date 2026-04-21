from fastapi import APIRouter, HTTPException, status

from autoagent.auth.jwt import create_access_token
from autoagent.auth.passwords import verify_password
from autoagent.config.settings import get_settings
from autoagent.models.api import LoginRequest, LoginResponse
from autoagent.storage.users import get_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest) -> LoginResponse:
    user = await get_user(req.username)
    if user is None or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token(req.username)
    return LoginResponse(token=token, expires_in_sec=get_settings().jwt_expires_hours * 3600)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout() -> None:
    # Stateless JWT; client simply drops token. Endpoint exists for UX/logging symmetry.
    return None
