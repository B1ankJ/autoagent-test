import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from autoagent.api.auth import router as auth_router
from autoagent.api.batches import router as batches_router
from autoagent.api.config import router as config_router
from autoagent.api.devices import router as devices_router
from autoagent.api.profiles import router as profiles_router
from autoagent.api.tests import router as tests_router
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
    yield


app = FastAPI(title="AutoAgent Test", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/v1")
app.include_router(profiles_router, prefix="/api/v1")
app.include_router(tests_router, prefix="/api/v1")
app.include_router(batches_router, prefix="/api/v1")
app.include_router(config_router, prefix="/api/v1")
app.include_router(devices_router, prefix="/api/v1")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
