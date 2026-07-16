from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    admin_username: str = Field(default="admin", min_length=1)
    # SecretStr so these never appear in tracebacks, repr(settings), or an
    # accidental log line — str(settings) / repr(settings) print "**********"
    # instead of the actual value. Callers must .get_secret_value().
    admin_password: SecretStr = Field(default=SecretStr("admin123456"))
    jwt_secret: SecretStr = Field(
        default=SecretStr("dev-secret-key-32-chars-minimum-length"), min_length=32
    )
    jwt_expires_hours: int = 24
    static_api_key: SecretStr | None = None

    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)

    data_root: Path = Path("./data")
    logs_root: Path = Path("./logs")
    adb_keyboard_apk_path: Path = Path(__file__).parent.parent / "fixtures" / "ADBKeyboard.apk"

    default_api_timeout_sec: int = 60
    default_gui_timeout_sec: int = 180
    default_retry: int = 2
    default_concurrency: int = 1
    # Off by default: verbose per-action screenshots/logging are useful while
    # debugging a profile but add meaningful disk/IO overhead at scale. Turn
    # on per-batch or via this default for a debugging session.
    default_verbose_logs: bool = False
    # How long an android sample waits for a free device before giving up.
    # Defaults to ~2h so concurrently-submitted batches queue behind each
    # other instead of failing fast after 60s.
    device_acquire_timeout_sec: float = 7200.0


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
