from fastapi import FastAPI

from autoagent.api.auth import router as auth_router

app = FastAPI(title="AutoAgent Test", version="0.1.0")
app.include_router(auth_router, prefix="/api/v1")
