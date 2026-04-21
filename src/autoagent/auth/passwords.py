from passlib.context import CryptContext
from passlib.exc import PasswordValueError, UnknownHashError

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plaintext: str) -> str:
    return _pwd_context.hash(plaintext)


def verify_password(plaintext: str, hashed: str) -> bool:
    try:
        return _pwd_context.verify(plaintext, hashed)
    except (UnknownHashError, PasswordValueError, ValueError):
        return False
