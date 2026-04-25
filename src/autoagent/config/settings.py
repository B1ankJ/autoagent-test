from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    admin_username: str = Field(default="admin", min_length=1)
    admin_password: str = Field(default="admin123456")
    jwt_secret: str = Field(default="dev-secret-key-32-chars-minimum-length", min_length=32)
    jwt_expires_hours: int = 24

    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)

    data_root: Path = Path("./data")
    logs_root: Path = Path("./logs")
    adb_keyboard_apk_path: Path = Path(__file__).parent.parent / "fixtures" / "ADBKeyboard.apk"

    default_api_timeout_sec: int = 60
    default_gui_timeout_sec: int = 180
    default_retry: int = 2
    default_concurrency: int = 1
    default_verbose_logs: bool = True


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
