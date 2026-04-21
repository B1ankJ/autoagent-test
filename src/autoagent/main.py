from fastapi import FastAPI

from autoagent.api.auth import router as auth_router
from autoagent.api.batches import router as batches_router
from autoagent.api.config import router as config_router
from autoagent.api.devices import router as devices_router
from autoagent.api.profiles import router as profiles_router
from autoagent.api.tests import router as tests_router

app = FastAPI(title="AutoAgent Test", version="0.1.0")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(profiles_router, prefix="/api/v1")
app.include_router(tests_router, prefix="/api/v1")
app.include_router(batches_router, prefix="/api/v1")
app.include_router(config_router, prefix="/api/v1")
app.include_router(devices_router, prefix="/api/v1")
