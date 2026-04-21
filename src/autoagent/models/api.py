from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    expires_in_sec: int
