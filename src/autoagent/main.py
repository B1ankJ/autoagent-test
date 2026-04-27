import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from autoagent.api._deps import get_device_monitor
from autoagent.api.auth import router as auth_router
from autoagent.api.batches import router as batches_router
from autoagent.api.config import router as config_router
from autoagent.api.devices import router as devices_router
from autoagent.api.profile_builder import router as profile_builder_router
from autoagent.api.profiles import router as profiles_router
from autoagent.api.tests import router as tests_router
from autoagent.api.web_profile_builder import router as web_profile_builder_router
from autoagent.auth.passwords import hash_password
from autoagent.config.settings import get_settings
from autoagent.storage.database import init_db
from autoagent.storage.users import get_user, upsert_user
from autoagent.utils.logging import configure_logging

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    await init_db()
    existing = await get_user(settings.admin_username)
    if existing is None:
        await upsert_user(settings.admin_username, hash_password(settings.admin_password))
        log.info("bootstrapped admin user %s", settings.admin_username)
    else:
        log.info("admin user %s already exists", settings.admin_username)
    monitor_task = asyncio.create_task(get_device_monitor().run())
    try:
        yield
    finally:
        monitor_task.cancel()
        with suppress(asyncio.CancelledError):
            await monitor_task


app = FastAPI(title="AutoAgent Test", version="0.1.0", lifespan=lifespan)

_cors_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(auth_router, prefix="/api/v1")
app.include_router(profiles_router, prefix="/api/v1")
app.include_router(tests_router, prefix="/api/v1")
app.include_router(batches_router, prefix="/api/v1")
app.include_router(config_router, prefix="/api/v1")
app.include_router(devices_router, prefix="/api/v1")
app.include_router(profile_builder_router, prefix="/api/v1")
app.include_router(web_profile_builder_router, prefix="/api/v1")


def _mount_static(app: FastAPI) -> None:
    static_dir = Path(os.environ.get("AUTOAGENT_STATIC_DIR", "src/autoagent/static"))
    index_file = static_dir / "index.html"
    if not index_file.exists():

        @app.get("/", include_in_schema=False)
        async def _ui_missing() -> dict:
            return {"status": "ok", "ui": "not_built"}

        return

    @app.get("/", include_in_schema=False)
    async def _index() -> FileResponse:
        return FileResponse(index_file)

    @app.get("/{path:path}", include_in_schema=False)
    async def _spa(path: str) -> FileResponse:
        if path.startswith("api/") or path == "health":
            raise HTTPException(status_code=404)

        candidate = static_dir / path
        if candidate.is_file():
            return FileResponse(candidate)

        return FileResponse(index_file)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


_mount_static(app)
