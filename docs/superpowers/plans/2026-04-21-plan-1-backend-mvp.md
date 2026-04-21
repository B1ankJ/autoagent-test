# Plan 1: Backend MVP — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a FastAPI-based backend that can load batches of test samples (JSONL/JSON/CSV), execute them against any OpenAI-compatible API, and deliver structured results — with authentication, async job tracking, webhooks, and persistent storage.

**Architecture:** Python 3.10+ / FastAPI async server, SQLite via async SQLAlchemy, asyncio-based scheduler with concurrency semaphore, pluggable Executor interface (API executor only in this plan; Web/Android in later plans), Pydantic for schemas, JWT bearer auth with a single bootstrap admin user. Source layout uses `src/autoagent/`.

**Tech Stack:** Python 3.10+, FastAPI, SQLAlchemy 2.x (async) + aiosqlite, Pydantic v2, PyJWT, passlib[bcrypt], httpx, openai SDK, PyYAML, uv (package manager), pytest + pytest-asyncio + pytest-httpx, ruff.

**Spec reference:** `docs/superpowers/specs/2026-04-21-agent-ai-testing-tool-design.md`

**Scope boundary:** Backend only. API mode only. No GUI executors, no Web UI, no Android. Profile schemas for Web/Android are defined but unused by executors in this plan. Those executors come in Plans 3–4.

---

## File Structure

```
AutoAgentTest/
├── .gitignore
├── pyproject.toml
├── .env.example
├── README.md
├── src/autoagent/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app entry
│   ├── config/
│   │   └── settings.py            # env + global defaults
│   ├── models/
│   │   ├── db.py                  # SQLAlchemy ORM tables
│   │   └── api.py                 # Pydantic API schemas
│   ├── storage/
│   │   ├── database.py            # engine, session, init_db
│   │   ├── batches.py             # batch CRUD
│   │   ├── samples.py             # sample CRUD
│   │   ├── users.py               # user CRUD
│   │   └── configs.py             # VLM/defaults key-value store
│   ├── auth/
│   │   ├── passwords.py           # bcrypt hash/verify
│   │   ├── jwt.py                 # encode/decode/expiry
│   │   └── deps.py                # FastAPI dependency require_user
│   ├── profiles/
│   │   ├── schemas.py             # Pydantic profile models
│   │   └── registry.py            # YAML load/save/validate
│   ├── loaders/
│   │   ├── jsonl_loader.py
│   │   ├── json_loader.py
│   │   └── csv_loader.py
│   ├── executors/
│   │   ├── base.py                # Executor interface + retry wrapper
│   │   └── api_executor.py        # OpenAI-compatible executor
│   ├── scheduler/
│   │   └── batch_scheduler.py     # asyncio queue + concurrency
│   ├── webhooks/
│   │   └── sender.py              # POST callback with retry
│   ├── results/
│   │   └── writer.py              # JSONL per batch
│   ├── api/
│   │   ├── auth.py                # /auth/*
│   │   ├── tests.py               # /tests/*
│   │   ├── batches.py             # /batches/*
│   │   ├── profiles.py            # /profiles/*
│   │   ├── config.py              # /config/*
│   │   └── devices.py             # /devices/* (stub)
│   └── utils/
│       ├── ids.py                 # id generators
│       └── logging.py             # structured logs
├── tests/
│   ├── conftest.py
│   ├── fixtures/
│   │   ├── batch_sample.jsonl
│   │   ├── batch_sample.json
│   │   └── batch_sample.csv
│   ├── unit/
│   │   ├── test_loaders.py
│   │   ├── test_api_executor.py
│   │   ├── test_scheduler.py
│   │   ├── test_auth.py
│   │   ├── test_profiles.py
│   │   ├── test_webhooks.py
│   │   └── test_result_writer.py
│   └── integration/
│       ├── test_auth_endpoints.py
│       ├── test_tests_endpoints.py
│       ├── test_batches_endpoints.py
│       ├── test_profiles_endpoints.py
│       ├── test_config_endpoints.py
│       └── test_e2e_batch.py
├── data/
│   ├── profiles/                  # user's YAML profiles
│   └── .gitkeep
├── logs/
│   └── .gitkeep
└── docs/
    └── superpowers/
        ├── specs/
        └── plans/
```

**Responsibility notes:**
- `storage/` is the only module that touches the DB; everything else goes through it
- `executors/` files are pluggable — `api_executor.py` is the only one in this plan
- `profiles/schemas.py` defines all three platform schemas (API/Web/Android) via Pydantic discriminated unions; only API is actively used
- `scheduler/batch_scheduler.py` owns the async queue, concurrency semaphore, and sample dispatch

---

## Task 1: Project skeleton + git init

**Files:**
- Create: `.gitignore`
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `src/autoagent/__init__.py` (empty)
- Create: `tests/__init__.py` (empty)
- Create: `README.md`
- Create: `data/.gitkeep`, `logs/.gitkeep`, `data/profiles/.gitkeep`

- [ ] **Step 1: Initialize git**

```bash
cd /Users/b1ankj/Desktop/2026/Q2/AutoAgentTest
git init
git config user.name "Developer"   # Skip if global already set
git config user.email "dev@local"
```

- [ ] **Step 2: Write `.gitignore`**

```
__pycache__/
*.py[cod]
.venv/
venv/
.env
*.egg-info/
build/
dist/
.pytest_cache/
.ruff_cache/
.coverage
htmlcov/
data/db.sqlite
data/db.sqlite-*
logs/*
!logs/.gitkeep
node_modules/
.DS_Store
.idea/
.vscode/
```

- [ ] **Step 3: Write `pyproject.toml`**

```toml
[project]
name = "autoagent"
version = "0.1.0"
description = "Automated Agent AI Testing Tool (backend MVP)"
requires-python = ">=3.10"
dependencies = [
  "fastapi>=0.110",
  "uvicorn[standard]>=0.27",
  "sqlalchemy[asyncio]>=2.0",
  "aiosqlite>=0.20",
  "pydantic>=2.5",
  "pydantic-settings>=2.1",
  "pyjwt>=2.8",
  "passlib[bcrypt]>=1.7",
  "httpx>=0.27",
  "openai>=1.12",
  "pyyaml>=6.0",
  "python-multipart>=0.0.9",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "pytest-asyncio>=0.23",
  "pytest-httpx>=0.30",
  "ruff>=0.3",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]

[tool.ruff]
line-length = 100
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "I", "W", "B", "UP"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 4: Write `.env.example`**

```
# Authentication
ADMIN_USERNAME=admin
ADMIN_PASSWORD=change_me_in_production
JWT_SECRET=replace_with_random_64_char_string
JWT_EXPIRES_HOURS=24

# Server
HOST=0.0.0.0
PORT=8000

# Storage
DATA_ROOT=./data
LOGS_ROOT=./logs

# Global defaults (can be overridden via /api/v1/config/defaults)
DEFAULT_API_TIMEOUT_SEC=60
DEFAULT_GUI_TIMEOUT_SEC=180
DEFAULT_RETRY=2
DEFAULT_CONCURRENCY=1
DEFAULT_VERBOSE_LOGS=true
```

- [ ] **Step 5: Create empty packages**

```bash
mkdir -p src/autoagent tests tests/unit tests/integration tests/fixtures data/profiles logs
touch src/autoagent/__init__.py tests/__init__.py tests/unit/__init__.py tests/integration/__init__.py
touch data/.gitkeep logs/.gitkeep data/profiles/.gitkeep
```

- [ ] **Step 6: Write `README.md`** (stub — expanded in Task 22)

```markdown
# AutoAgent Test

Automated Agent AI testing tool — backend MVP.

## Setup

```bash
pip install -e ".[dev]"
cp .env.example .env
# Edit .env, set ADMIN_PASSWORD and JWT_SECRET
uvicorn autoagent.main:app --reload
```

See `docs/superpowers/specs/` and `docs/superpowers/plans/` for architecture.
```

- [ ] **Step 7: Install + initial commit**

```bash
pip install -e ".[dev]"
git add .
git commit -m "chore: project skeleton and build config"
```

Expected: install succeeds, commit created.

---

## Task 2: Settings / env config

**Files:**
- Create: `src/autoagent/config/__init__.py`
- Create: `src/autoagent/config/settings.py`
- Create: `tests/unit/test_settings.py`

- [ ] **Step 1: Write failing test `tests/unit/test_settings.py`**

```python
import os
from autoagent.config.settings import get_settings


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "root")
    monkeypatch.setenv("ADMIN_PASSWORD", "pw")
    monkeypatch.setenv("JWT_SECRET", "s" * 32)
    monkeypatch.setenv("DEFAULT_API_TIMEOUT_SEC", "90")
    get_settings.cache_clear()
    s = get_settings()
    assert s.admin_username == "root"
    assert s.admin_password == "pw"
    assert s.default_api_timeout_sec == 90


def test_missing_jwt_secret_fails(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setenv("ADMIN_USERNAME", "a")
    monkeypatch.setenv("ADMIN_PASSWORD", "b")
    get_settings.cache_clear()
    import pytest
    with pytest.raises(Exception):
        get_settings()
```

- [ ] **Step 2: Run test, verify fail**

Run: `pytest tests/unit/test_settings.py -v`
Expected: ImportError / ModuleNotFoundError.

- [ ] **Step 3: Write `src/autoagent/config/settings.py`**

```python
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    admin_username: str
    admin_password: str
    jwt_secret: str = Field(min_length=32)
    jwt_expires_hours: int = 24

    host: str = "0.0.0.0"
    port: int = 8000

    data_root: Path = Path("./data")
    logs_root: Path = Path("./logs")

    default_api_timeout_sec: int = 60
    default_gui_timeout_sec: int = 180
    default_retry: int = 2
    default_concurrency: int = 1
    default_verbose_logs: bool = True


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Create package init**

```python
# src/autoagent/config/__init__.py
from autoagent.config.settings import Settings, get_settings

__all__ = ["Settings", "get_settings"]
```

- [ ] **Step 5: Run tests, verify pass**

Run: `pytest tests/unit/test_settings.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add src/autoagent/config tests/unit/test_settings.py
git commit -m "feat(config): settings loader with env and defaults"
```

---

## Task 3: Database bootstrap (async SQLAlchemy + SQLite)

**Files:**
- Create: `src/autoagent/models/__init__.py`
- Create: `src/autoagent/models/db.py`
- Create: `src/autoagent/storage/__init__.py`
- Create: `src/autoagent/storage/database.py`
- Create: `tests/unit/test_database.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Write `src/autoagent/models/db.py` — ORM tables**

```python
from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime, Float, func
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    username = Column(String, primary_key=True)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class Batch(Base):
    __tablename__ = "batches"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    mode = Column(String, nullable=False)
    status = Column(String, nullable=False, default="queued")  # queued|running|done|failed|cancelled
    concurrency = Column(Integer, nullable=False, default=1)
    total = Column(Integer, nullable=False, default=0)
    done = Column(Integer, nullable=False, default=0)
    failed = Column(Integer, nullable=False, default=0)
    avg_duration_ms = Column(Integer, nullable=True)
    total_duration_ms = Column(Integer, nullable=True)
    target_profile_default = Column(String, nullable=True)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class Sample(Base):
    __tablename__ = "samples"
    batch_id = Column(String, primary_key=True)
    id = Column(String, primary_key=True)
    status = Column(String, nullable=False, default="queued")  # queued|running|done|failed|timeout|extraction_failed|cancelled
    prompts_sent_json = Column(Text, nullable=True)
    responses_json = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    mode = Column(String, nullable=False)
    target_profile = Column(String, nullable=False)
    metadata_json = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    logs_dir = Column(String, nullable=True)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)


class ConfigKV(Base):
    __tablename__ = "configs"
    key = Column(String, primary_key=True)
    value_json = Column(Text, nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
```

- [ ] **Step 2: Write `src/autoagent/storage/database.py`**

```python
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from autoagent.config.settings import get_settings
from autoagent.models.db import Base

_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _db_url() -> str:
    settings = get_settings()
    db_path = settings.data_root / "db.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{db_path}"


def get_engine():
    global _engine, _sessionmaker
    if _engine is None:
        _engine = create_async_engine(_db_url(), echo=False, future=True)
        _sessionmaker = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def init_db() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def reset_db_for_tests() -> None:
    """Drop all and recreate. ONLY for tests."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
```

- [ ] **Step 3: Write `tests/conftest.py`**

```python
import asyncio
import os
import tempfile
from pathlib import Path

import pytest

@pytest.fixture(autouse=True)
def _env_defaults(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin_pw_1234")
    monkeypatch.setenv("JWT_SECRET", "x" * 64)
    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("LOGS_ROOT", str(tmp_path / "logs"))
    from autoagent.config.settings import get_settings
    get_settings.cache_clear()
    # Reset DB singletons so fresh tmp path is used
    import autoagent.storage.database as db_mod
    db_mod._engine = None
    db_mod._sessionmaker = None
    yield
    get_settings.cache_clear()
```

- [ ] **Step 4: Write `tests/unit/test_database.py`**

```python
import pytest

from autoagent.storage.database import get_sessionmaker, init_db
from autoagent.models.db import User


@pytest.mark.asyncio
async def test_init_db_creates_users_table():
    await init_db()
    sm = get_sessionmaker()
    async with sm() as s:
        u = User(username="x", password_hash="h")
        s.add(u)
        await s.commit()

    async with sm() as s:
        result = await s.get(User, "x")
        assert result is not None
        assert result.username == "x"
```

- [ ] **Step 5: Create package inits**

```python
# src/autoagent/models/__init__.py
# (empty)

# src/autoagent/storage/__init__.py
# (empty)
```

- [ ] **Step 6: Run tests, verify pass**

Run: `pytest tests/unit/test_database.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/autoagent/models src/autoagent/storage tests/conftest.py tests/unit/test_database.py
git commit -m "feat(storage): async SQLAlchemy engine and ORM tables"
```

---

## Task 4: User storage + password hashing + bootstrap admin

**Files:**
- Create: `src/autoagent/auth/__init__.py`
- Create: `src/autoagent/auth/passwords.py`
- Create: `src/autoagent/storage/users.py`
- Create: `tests/unit/test_auth.py`

- [ ] **Step 1: Write failing tests `tests/unit/test_auth.py` (passwords portion)**

```python
import pytest
from autoagent.auth.passwords import hash_password, verify_password


def test_hash_and_verify_password():
    h = hash_password("hunter2")
    assert h != "hunter2"
    assert verify_password("hunter2", h) is True
    assert verify_password("wrong", h) is False
```

- [ ] **Step 2: Run tests, verify fail**

Run: `pytest tests/unit/test_auth.py -v`
Expected: ImportError.

- [ ] **Step 3: Write `src/autoagent/auth/passwords.py`**

```python
from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plaintext: str) -> str:
    return _pwd_context.hash(plaintext)


def verify_password(plaintext: str, hashed: str) -> bool:
    try:
        return _pwd_context.verify(plaintext, hashed)
    except Exception:
        return False
```

- [ ] **Step 4: Write `src/autoagent/storage/users.py`**

```python
from sqlalchemy import select

from autoagent.models.db import User
from autoagent.storage.database import get_sessionmaker


async def get_user(username: str) -> User | None:
    sm = get_sessionmaker()
    async with sm() as s:
        r = await s.execute(select(User).where(User.username == username))
        return r.scalar_one_or_none()


async def create_user(username: str, password_hash: str) -> User:
    sm = get_sessionmaker()
    async with sm() as s:
        u = User(username=username, password_hash=password_hash)
        s.add(u)
        await s.commit()
        return u


async def upsert_user(username: str, password_hash: str) -> None:
    sm = get_sessionmaker()
    async with sm() as s:
        existing = await s.get(User, username)
        if existing is None:
            s.add(User(username=username, password_hash=password_hash))
        else:
            existing.password_hash = password_hash
        await s.commit()
```

- [ ] **Step 5: Add bootstrap test**

Append to `tests/unit/test_auth.py`:

```python
from autoagent.auth.passwords import hash_password
from autoagent.storage.database import init_db
from autoagent.storage.users import create_user, get_user


@pytest.mark.asyncio
async def test_user_round_trip():
    await init_db()
    h = hash_password("pw")
    await create_user("alice", h)
    u = await get_user("alice")
    assert u is not None
    assert u.username == "alice"
```

- [ ] **Step 6: Run all tests, verify pass**

Run: `pytest tests/unit/test_auth.py -v`
Expected: 2 passed.

- [ ] **Step 7: Commit**

```bash
git add src/autoagent/auth src/autoagent/storage/users.py tests/unit/test_auth.py
git commit -m "feat(auth): password hashing and user storage"
```

---

## Task 5: JWT utils + auth dependency

**Files:**
- Create: `src/autoagent/auth/jwt.py`
- Create: `src/autoagent/auth/deps.py`
- Modify: `tests/unit/test_auth.py` (add JWT cases)

- [ ] **Step 1: Extend `tests/unit/test_auth.py`**

```python
from datetime import datetime, timedelta, timezone

from autoagent.auth.jwt import create_access_token, decode_token


def test_jwt_round_trip():
    token = create_access_token("alice")
    payload = decode_token(token)
    assert payload["sub"] == "alice"
    assert "exp" in payload


def test_jwt_expired_rejected(monkeypatch):
    import autoagent.auth.jwt as jwt_mod

    # Force immediate expiry
    monkeypatch.setattr(jwt_mod, "_expiry_hours", lambda: -1)
    token = create_access_token("alice")
    import pytest
    with pytest.raises(Exception):
        decode_token(token)
```

- [ ] **Step 2: Write `src/autoagent/auth/jwt.py`**

```python
from datetime import datetime, timedelta, timezone

import jwt

from autoagent.config.settings import get_settings

ALG = "HS256"


def _secret() -> str:
    return get_settings().jwt_secret


def _expiry_hours() -> int:
    return get_settings().jwt_expires_hours


def create_access_token(username: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=_expiry_hours())).timestamp()),
    }
    return jwt.encode(payload, _secret(), algorithm=ALG)


def decode_token(token: str) -> dict:
    return jwt.decode(token, _secret(), algorithms=[ALG])
```

- [ ] **Step 3: Write `src/autoagent/auth/deps.py`**

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from autoagent.auth.jwt import decode_token

_bearer = HTTPBearer(auto_error=False)


async def require_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        payload = decode_token(creds.credentials)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    sub = payload.get("sub")
    if not isinstance(sub, str):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token")
    return sub
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/unit/test_auth.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/autoagent/auth/jwt.py src/autoagent/auth/deps.py tests/unit/test_auth.py
git commit -m "feat(auth): JWT create/decode and FastAPI bearer dependency"
```

---

## Task 6: Auth API endpoints (login/logout)

**Files:**
- Create: `src/autoagent/api/__init__.py`
- Create: `src/autoagent/models/api.py` (start, expand in Task 7)
- Create: `src/autoagent/api/auth.py`
- Create: `tests/integration/test_auth_endpoints.py`

- [ ] **Step 1: Write `src/autoagent/models/api.py` (auth models only)**

```python
from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    expires_in_sec: int
```

- [ ] **Step 2: Write `src/autoagent/api/auth.py`**

```python
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
```

- [ ] **Step 3: Write `tests/integration/test_auth_endpoints.py`**

```python
import pytest
from httpx import ASGITransport, AsyncClient

from autoagent.auth.passwords import hash_password
from autoagent.storage.database import init_db
from autoagent.storage.users import upsert_user


@pytest.fixture
async def client():
    await init_db()
    await upsert_user("admin", hash_password("admin_pw_1234"))
    from autoagent.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def test_login_success(client):
    r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin_pw_1234"})
    assert r.status_code == 200
    body = r.json()
    assert "token" in body
    assert body["expires_in_sec"] > 0


async def test_login_bad_password(client):
    r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401


async def test_login_unknown_user(client):
    r = await client.post("/api/v1/auth/login", json={"username": "nobody", "password": "x"})
    assert r.status_code == 401
```

- [ ] **Step 4: Stub `src/autoagent/main.py` so import resolves**

```python
from fastapi import FastAPI

from autoagent.api.auth import router as auth_router

app = FastAPI(title="AutoAgent Test", version="0.1.0")
app.include_router(auth_router, prefix="/api/v1")
```

- [ ] **Step 5: Run tests, verify pass**

Run: `pytest tests/integration/test_auth_endpoints.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add src/autoagent/api/__init__.py src/autoagent/api/auth.py src/autoagent/models/api.py src/autoagent/main.py tests/integration/test_auth_endpoints.py
git commit -m "feat(api): auth login/logout endpoints"
```

---

## Task 7: Pydantic schemas for Sample / Batch / Result

**Files:**
- Modify: `src/autoagent/models/api.py`
- Create: `tests/unit/test_api_schemas.py`

- [ ] **Step 1: Write failing tests `tests/unit/test_api_schemas.py`**

```python
import pytest
from pydantic import ValidationError

from autoagent.models.api import Sample, SampleResult, BatchCreateJSON, BatchSummary


def test_sample_defaults():
    s = Sample(id="t1", prompts=["hi"], mode="api", target_profile="p")
    assert s.new_session is True
    assert s.retry == 2
    assert s.dry_run is False
    assert s.metadata == {}


def test_sample_requires_prompts():
    with pytest.raises(ValidationError):
        Sample(id="t1", prompts=[], mode="api", target_profile="p")


def test_sample_mode_enum():
    with pytest.raises(ValidationError):
        Sample(id="t1", prompts=["x"], mode="bogus", target_profile="p")


def test_sample_result_roundtrip():
    r = SampleResult(
        id="t1", status="done", prompts_sent=["hi"], responses=["hello"],
        duration_ms=100, attempt_count=1, mode="api", target_profile="p",
    )
    assert r.model_dump()["status"] == "done"


def test_batch_create_requires_same_mode():
    with pytest.raises(ValidationError):
        BatchCreateJSON(
            name="b", mode="api",
            samples=[
                Sample(id="t1", prompts=["x"], mode="api", target_profile="p"),
                Sample(id="t2", prompts=["y"], mode="gui_pc_web", target_profile="p"),
            ],
        )


def test_batch_summary():
    b = BatchSummary(batch_id="b1", name="n", mode="api", total=10, done=9, failed=1)
    assert b.avg_duration_ms is None
```

- [ ] **Step 2: Run tests, verify fail**

Run: `pytest tests/unit/test_api_schemas.py -v`
Expected: ImportError.

- [ ] **Step 3: Replace `src/autoagent/models/api.py`**

```python
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

Mode = Literal["api", "gui_pc_web", "gui_android"]
SampleStatus = Literal[
    "queued", "running", "done", "failed", "timeout", "extraction_failed", "cancelled"
]
BatchStatus = Literal["queued", "running", "done", "failed", "cancelled"]


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    expires_in_sec: int


class Sample(BaseModel):
    id: str
    prompts: list[str] = Field(min_length=1)
    mode: Mode
    target_profile: str
    new_session: bool = True
    timeout_sec: int | None = None
    retry: int = 2
    dry_run: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    callback_url: str | None = None


class SampleResult(BaseModel):
    id: str
    status: SampleStatus
    prompts_sent: list[str] = Field(default_factory=list)
    responses: list[str] = Field(default_factory=list)
    duration_ms: int | None = None
    attempt_count: int = 0
    mode: Mode
    target_profile: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    logs_dir: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None


class BatchCreateJSON(BaseModel):
    name: str
    mode: Mode
    concurrency: int = 1
    target_profile_default: str | None = None
    samples: list[Sample]

    @model_validator(mode="after")
    def _modes_match(self) -> "BatchCreateJSON":
        for s in self.samples:
            if s.mode != self.mode:
                raise ValueError(f"sample {s.id} mode={s.mode} differs from batch mode={self.mode}")
        return self


class BatchCreatedResponse(BaseModel):
    batch_id: str


class BatchSummary(BaseModel):
    batch_id: str
    name: str
    mode: Mode
    status: BatchStatus = "queued"
    total: int
    done: int
    failed: int
    avg_duration_ms: int | None = None
    total_duration_ms: int | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None


class BatchDetail(BatchSummary):
    samples: list[SampleResult] = Field(default_factory=list)


class AsyncTestResponse(BaseModel):
    task_id: str
    status: Literal["queued"] = "queued"


class VLMConfig(BaseModel):
    base_url: str
    model: str
    api_key_env: str = "VLM_API_KEY"
    extra_headers: dict[str, str] = Field(default_factory=dict)


class DefaultsConfig(BaseModel):
    api_timeout_sec: int = 60
    gui_timeout_sec: int = 180
    retry: int = 2
    concurrency: int = 1
    verbose_logs: bool = True
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/unit/test_api_schemas.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/autoagent/models/api.py tests/unit/test_api_schemas.py
git commit -m "feat(models): Sample/Batch/Result pydantic schemas with validators"
```

---

## Task 8: Profile schemas (Pydantic discriminated union)

**Files:**
- Create: `src/autoagent/profiles/__init__.py`
- Create: `src/autoagent/profiles/schemas.py`
- Create: `tests/unit/test_profiles.py`

- [ ] **Step 1: Write failing tests `tests/unit/test_profiles.py` (schemas portion)**

```python
import pytest
from pydantic import ValidationError

from autoagent.profiles.schemas import parse_profile, ApiProfile, WebProfile, AndroidProfile


def test_parse_api_profile():
    p = parse_profile({
        "name": "openai_gpt4",
        "platform": "api",
        "api": {
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o",
            "api_key_env": "OPENAI_KEY",
        },
    })
    assert isinstance(p, ApiProfile)
    assert p.api.model == "gpt-4o"


def test_parse_web_profile():
    p = parse_profile({
        "name": "chatgpt_web",
        "platform": "web",
        "url": "https://chat.openai.com",
        "ready_check": {"type": "dom_selector", "selector": "textarea"},
        "recovery_path": [],
        "input_selector": "textarea",
        "send_method": {"type": "keyboard", "key": "Enter"},
        "response_container_selector": "div.assistant",
        "complete_detection": {"type": "dom_stable", "stable_sec": 2, "max_wait_sec": 120},
    })
    assert isinstance(p, WebProfile)


def test_parse_android_profile():
    p = parse_profile({
        "name": "wechat_bot",
        "platform": "android",
        "package": "com.tencent.mm",
        "ready_check": {"type": "ui_tree_contains", "text": "Bot"},
        "recovery_path": [],
        "input_locator": {"type": "resource_id", "value": "com.tencent.mm:id/edit"},
        "send_button_locator": {"type": "text", "value": "Send"},
        "response_extraction": {
            "method": "ui_tree_then_ocr",
            "response_container_locator": {"type": "resource_id", "value": "x"},
            "scroll_container_locator": {"type": "resource_id", "value": "x"},
            "latest_bubble_match": {"type": "last_child_with_class", "value": "TextView"},
        },
        "complete_detection": {"type": "pixel_stable", "stable_sec": 3, "max_wait_sec": 180},
    })
    assert isinstance(p, AndroidProfile)


def test_invalid_platform_rejected():
    with pytest.raises(ValidationError):
        parse_profile({"name": "x", "platform": "ios"})
```

- [ ] **Step 2: Write `src/autoagent/profiles/schemas.py`**

```python
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter


# ---- shared fragments ----

class Locator(BaseModel):
    type: Literal["resource_id", "text", "xpath", "class", "last_child_with_class"]
    value: str


class ActionStep(BaseModel):
    action: str
    # free-form kwargs; platform-specific validation happens at runtime
    model_config = {"extra": "allow"}


class DomStable(BaseModel):
    type: Literal["dom_stable"]
    stable_sec: float = 2
    max_wait_sec: float = 120


class UiTreeStable(BaseModel):
    type: Literal["ui_tree_stable"]
    stable_sec: float = 2
    max_wait_sec: float = 180


class PixelStable(BaseModel):
    type: Literal["pixel_stable"]
    stable_sec: float = 3
    max_wait_sec: float = 180


class SendButtonReenable(BaseModel):
    type: Literal["send_button_reenable"]


CompleteDetection = Annotated[
    Union[DomStable, UiTreeStable, PixelStable, SendButtonReenable],
    Field(discriminator="type"),
]


# ---- API profile ----

class ApiConfig(BaseModel):
    base_url: str
    model: str
    api_key_env: str
    extra_headers: dict[str, str] = Field(default_factory=dict)
    temperature: float | None = None
    max_tokens: int | None = None


class ApiProfile(BaseModel):
    name: str
    platform: Literal["api"]
    api: ApiConfig
    multi_turn_mode: Literal["history", "single"] = "history"


# ---- Web profile ----

class WebReadyCheck(BaseModel):
    type: Literal["dom_selector"]
    selector: str
    timeout_sec: float = 5


class WebSendMethodKeyboard(BaseModel):
    type: Literal["keyboard"]
    key: str = "Enter"


class WebSendMethodClick(BaseModel):
    type: Literal["click_button"]
    selector: str


WebSendMethod = Annotated[
    Union[WebSendMethodKeyboard, WebSendMethodClick],
    Field(discriminator="type"),
]


class WebBrowserConfig(BaseModel):
    headless: bool = False
    user_data_dir: str | None = None


class WebProfile(BaseModel):
    name: str
    platform: Literal["web"]
    url: str
    browser: WebBrowserConfig = Field(default_factory=WebBrowserConfig)
    ready_check: WebReadyCheck
    recovery_path: list[ActionStep]
    input_selector: str
    send_method: WebSendMethod
    response_container_selector: str
    new_session_action: list[ActionStep] = Field(default_factory=list)
    complete_detection: CompleteDetection


# ---- Android profile ----

class AndroidReadyCheckTree(BaseModel):
    type: Literal["ui_tree_contains"]
    text: str
    timeout_sec: float = 5


class AndroidResponseExtraction(BaseModel):
    method: Literal["ui_tree_only", "ocr_only", "ui_tree_then_ocr"]
    response_container_locator: Locator
    scroll_container_locator: Locator
    latest_bubble_match: Locator


class AndroidProfile(BaseModel):
    name: str
    platform: Literal["android"]
    package: str
    activity: str | None = None
    ready_check: AndroidReadyCheckTree
    recovery_path: list[ActionStep]
    input_locator: Locator
    send_button_locator: Locator
    response_extraction: AndroidResponseExtraction
    new_session_action: list[ActionStep] = Field(default_factory=list)
    complete_detection: CompleteDetection


# ---- Union + parser ----

Profile = Annotated[
    Union[ApiProfile, WebProfile, AndroidProfile],
    Field(discriminator="platform"),
]

_profile_adapter: TypeAdapter[Profile] = TypeAdapter(Profile)


def parse_profile(data: dict[str, Any]) -> Profile:
    return _profile_adapter.validate_python(data)
```

- [ ] **Step 3: Run tests, verify pass**

Run: `pytest tests/unit/test_profiles.py -v`
Expected: 4 passed.

- [ ] **Step 4: Commit**

```bash
git add src/autoagent/profiles/__init__.py src/autoagent/profiles/schemas.py tests/unit/test_profiles.py
git commit -m "feat(profiles): API/Web/Android profile schemas with discriminated union"
```

---

## Task 9: Profile registry (YAML file storage)

**Files:**
- Create: `src/autoagent/profiles/registry.py`
- Modify: `tests/unit/test_profiles.py`

- [ ] **Step 1: Extend `tests/unit/test_profiles.py`**

```python
import pytest
import yaml
from pathlib import Path

from autoagent.config.settings import get_settings
from autoagent.profiles.registry import (
    list_profile_names, load_profile, save_profile_yaml, delete_profile,
    validate_yaml,
)


def _api_yaml(name="openai_gpt4") -> str:
    return yaml.safe_dump({
        "name": name, "platform": "api",
        "api": {"base_url": "https://x", "model": "m", "api_key_env": "K"},
    })


def test_save_and_load_profile():
    save_profile_yaml("openai_gpt4", _api_yaml())
    names = list_profile_names()
    assert "openai_gpt4" in names
    p = load_profile("openai_gpt4")
    assert p.platform == "api"


def test_load_missing_returns_none():
    assert load_profile("ghost") is None


def test_delete_profile():
    save_profile_yaml("to_delete", _api_yaml("to_delete"))
    assert "to_delete" in list_profile_names()
    delete_profile("to_delete")
    assert "to_delete" not in list_profile_names()


def test_validate_yaml_accepts_good():
    ok, err = validate_yaml(_api_yaml())
    assert ok is True and err is None


def test_validate_yaml_rejects_bad():
    bad = "name: x\nplatform: unknown\n"
    ok, err = validate_yaml(bad)
    assert ok is False and err is not None
```

- [ ] **Step 2: Write `src/autoagent/profiles/registry.py`**

```python
from pathlib import Path

import yaml

from autoagent.config.settings import get_settings
from autoagent.profiles.schemas import Profile, parse_profile


def _dir() -> Path:
    d = get_settings().data_root / "profiles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(name: str) -> Path:
    if "/" in name or ".." in name or name == "":
        raise ValueError(f"invalid profile name: {name!r}")
    return _dir() / f"{name}.yaml"


def list_profile_names() -> list[str]:
    return sorted(p.stem for p in _dir().glob("*.yaml"))


def load_profile(name: str) -> Profile | None:
    path = _path(name)
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return parse_profile(data)


def load_profile_yaml(name: str) -> str | None:
    path = _path(name)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def save_profile_yaml(name: str, yaml_text: str) -> Profile:
    # Validate before writing
    data = yaml.safe_load(yaml_text)
    if not isinstance(data, dict):
        raise ValueError("YAML must be a mapping")
    # Enforce name consistency
    data["name"] = name
    profile = parse_profile(data)
    _path(name).write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return profile


def delete_profile(name: str) -> bool:
    path = _path(name)
    if path.exists():
        path.unlink()
        return True
    return False


def validate_yaml(yaml_text: str) -> tuple[bool, str | None]:
    try:
        data = yaml.safe_load(yaml_text)
        if not isinstance(data, dict):
            return False, "YAML root must be a mapping"
        parse_profile(data)
        return True, None
    except Exception as e:
        return False, str(e)
```

- [ ] **Step 3: Run tests, verify pass**

Run: `pytest tests/unit/test_profiles.py -v`
Expected: 9 passed (4 from Task 8 + 5 new).

- [ ] **Step 4: Commit**

```bash
git add src/autoagent/profiles/registry.py tests/unit/test_profiles.py
git commit -m "feat(profiles): YAML-backed registry with validation"
```

---

## Task 10: Profile API endpoints

**Files:**
- Create: `src/autoagent/api/profiles.py`
- Modify: `src/autoagent/main.py`
- Create: `tests/integration/test_profiles_endpoints.py`

- [ ] **Step 1: Write `src/autoagent/api/profiles.py`**

```python
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from autoagent.auth.deps import require_user
from autoagent.profiles.registry import (
    delete_profile as _delete,
    list_profile_names,
    load_profile_yaml,
    save_profile_yaml,
    validate_yaml,
)

router = APIRouter(prefix="/profiles", tags=["profiles"], dependencies=[Depends(require_user)])


class ProfileBody(BaseModel):
    yaml: str


class ProfileListResponse(BaseModel):
    names: list[str]


class ProfileYamlResponse(BaseModel):
    name: str
    yaml: str


class ValidateResponse(BaseModel):
    ok: bool
    error: str | None = None


@router.get("", response_model=ProfileListResponse)
async def list_profiles() -> ProfileListResponse:
    return ProfileListResponse(names=list_profile_names())


@router.get("/{name}", response_model=ProfileYamlResponse)
async def get_profile(name: str) -> ProfileYamlResponse:
    text = load_profile_yaml(name)
    if text is None:
        raise HTTPException(status_code=404, detail="profile not found")
    return ProfileYamlResponse(name=name, yaml=text)


@router.post("/{name}", status_code=status.HTTP_201_CREATED)
async def create_profile(name: str, body: ProfileBody) -> dict:
    try:
        save_profile_yaml(name, body.yaml)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"name": name}


@router.put("/{name}")
async def update_profile(name: str, body: ProfileBody) -> dict:
    try:
        save_profile_yaml(name, body.yaml)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"name": name}


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def del_profile(name: str) -> None:
    if not _delete(name):
        raise HTTPException(status_code=404, detail="profile not found")


@router.post("/validate", response_model=ValidateResponse)
async def validate_profile(body: ProfileBody) -> ValidateResponse:
    ok, err = validate_yaml(body.yaml)
    return ValidateResponse(ok=ok, error=err)
```

- [ ] **Step 2: Update `src/autoagent/main.py` to include router**

```python
from fastapi import FastAPI

from autoagent.api.auth import router as auth_router
from autoagent.api.profiles import router as profiles_router

app = FastAPI(title="AutoAgent Test", version="0.1.0")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(profiles_router, prefix="/api/v1")
```

- [ ] **Step 3: Write `tests/integration/test_profiles_endpoints.py`**

```python
import pytest
import yaml
from httpx import ASGITransport, AsyncClient

from autoagent.auth.passwords import hash_password
from autoagent.storage.database import init_db
from autoagent.storage.users import upsert_user


@pytest.fixture
async def client():
    await init_db()
    await upsert_user("admin", hash_password("admin_pw_1234"))
    from autoagent.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _login(client) -> str:
    r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin_pw_1234"})
    return r.json()["token"]


async def test_profiles_crud(client):
    token = await _login(client)
    h = {"Authorization": f"Bearer {token}"}

    profile_yaml = yaml.safe_dump({
        "name": "openai_gpt4", "platform": "api",
        "api": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o", "api_key_env": "OPENAI_KEY"},
    })

    # List initially empty
    r = await client.get("/api/v1/profiles", headers=h)
    assert r.status_code == 200
    assert r.json()["names"] == []

    # Create
    r = await client.post("/api/v1/profiles/openai_gpt4", json={"yaml": profile_yaml}, headers=h)
    assert r.status_code == 201

    # List shows it
    r = await client.get("/api/v1/profiles", headers=h)
    assert "openai_gpt4" in r.json()["names"]

    # Get
    r = await client.get("/api/v1/profiles/openai_gpt4", headers=h)
    assert r.status_code == 200
    assert "openai_gpt4" in r.json()["yaml"]

    # Validate (good)
    r = await client.post("/api/v1/profiles/validate", json={"yaml": profile_yaml}, headers=h)
    assert r.json() == {"ok": True, "error": None}

    # Validate (bad)
    r = await client.post("/api/v1/profiles/validate", json={"yaml": "name: x\nplatform: ios\n"}, headers=h)
    assert r.json()["ok"] is False

    # Delete
    r = await client.delete("/api/v1/profiles/openai_gpt4", headers=h)
    assert r.status_code == 204

    # Gone
    r = await client.get("/api/v1/profiles/openai_gpt4", headers=h)
    assert r.status_code == 404


async def test_profiles_require_auth(client):
    r = await client.get("/api/v1/profiles")
    assert r.status_code == 401
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/integration/test_profiles_endpoints.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/autoagent/api/profiles.py src/autoagent/main.py tests/integration/test_profiles_endpoints.py
git commit -m "feat(api): profiles CRUD endpoints with JWT auth"
```

---

## Task 11: Batch file loaders (JSONL + JSON + CSV)

**Files:**
- Create: `src/autoagent/loaders/__init__.py`
- Create: `src/autoagent/loaders/jsonl_loader.py`
- Create: `src/autoagent/loaders/json_loader.py`
- Create: `src/autoagent/loaders/csv_loader.py`
- Create: `tests/fixtures/batch_sample.jsonl`, `batch_sample.json`, `batch_sample.csv`
- Create: `tests/unit/test_loaders.py`

- [ ] **Step 1: Write fixture files**

`tests/fixtures/batch_sample.jsonl`:
```
{"id": "t1", "prompts": ["hello"], "mode": "api", "target_profile": "p"}
{"id": "t2", "prompts": ["hi", "再说一遍"], "mode": "api", "target_profile": "p", "new_session": false, "metadata": {"tag": "multi"}}
```

`tests/fixtures/batch_sample.json`:
```json
[
  {"id": "t1", "prompts": ["hello"], "mode": "api", "target_profile": "p"},
  {"id": "t2", "prompts": ["hi", "again"], "mode": "api", "target_profile": "p", "new_session": false}
]
```

`tests/fixtures/batch_sample.csv`:
```
id,prompts,mode,target_profile,new_session,metadata
t1,hello,api,p,true,
t2,"hi\u241fagain",api,p,false,"{""tag"":""multi""}"
```

- [ ] **Step 2: Write failing tests `tests/unit/test_loaders.py`**

```python
from pathlib import Path

import pytest

from autoagent.loaders.jsonl_loader import load_jsonl
from autoagent.loaders.json_loader import load_json
from autoagent.loaders.csv_loader import load_csv

FIX = Path(__file__).parent.parent / "fixtures"


def test_load_jsonl():
    samples = load_jsonl((FIX / "batch_sample.jsonl").read_text())
    assert len(samples) == 2
    assert samples[0].id == "t1"
    assert samples[1].prompts == ["hi", "再说一遍"]
    assert samples[1].new_session is False
    assert samples[1].metadata == {"tag": "multi"}


def test_load_json():
    samples = load_json((FIX / "batch_sample.json").read_text())
    assert len(samples) == 2
    assert samples[0].prompts == ["hello"]


def test_load_csv():
    samples = load_csv((FIX / "batch_sample.csv").read_text())
    assert len(samples) == 2
    assert samples[1].prompts == ["hi", "again"]
    assert samples[1].new_session is False
    assert samples[1].metadata == {"tag": "multi"}


def test_load_jsonl_empty_raises():
    with pytest.raises(ValueError):
        load_jsonl("")


def test_load_json_non_list_raises():
    with pytest.raises(ValueError):
        load_json('{"hello": "world"}')
```

- [ ] **Step 3: Write `src/autoagent/loaders/jsonl_loader.py`**

```python
import json

from autoagent.models.api import Sample


def load_jsonl(text: str) -> list[Sample]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ValueError("empty JSONL input")
    out: list[Sample] = []
    for i, line in enumerate(lines):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"line {i + 1}: invalid JSON ({e})") from e
        out.append(Sample.model_validate(obj))
    return out
```

- [ ] **Step 4: Write `src/autoagent/loaders/json_loader.py`**

```python
import json

from autoagent.models.api import Sample


def load_json(text: str) -> list[Sample]:
    data = json.loads(text)
    # Accept either a bare list of samples or {"samples": [...]}
    if isinstance(data, dict) and "samples" in data:
        data = data["samples"]
    if not isinstance(data, list):
        raise ValueError("JSON must be a list of samples or an object with 'samples' key")
    return [Sample.model_validate(s) for s in data]
```

- [ ] **Step 5: Write `src/autoagent/loaders/csv_loader.py`**

```python
import csv
import io
import json

from autoagent.models.api import Sample

PROMPT_SEP = "\u241f"  # Unit Separator


def _parse_bool(v: str) -> bool:
    return v.strip().lower() in {"1", "true", "yes", "y", "t"}


def load_csv(text: str) -> list[Sample]:
    reader = csv.DictReader(io.StringIO(text))
    out: list[Sample] = []
    for row in reader:
        prompts = [p for p in row["prompts"].split(PROMPT_SEP) if p != ""]
        md_raw = (row.get("metadata") or "").strip()
        md = json.loads(md_raw) if md_raw else {}
        s = Sample.model_validate({
            "id": row["id"],
            "prompts": prompts,
            "mode": row["mode"],
            "target_profile": row["target_profile"],
            "new_session": _parse_bool(row.get("new_session", "true")),
            "metadata": md,
        })
        out.append(s)
    return out
```

- [ ] **Step 6: Run tests, verify pass**

Run: `pytest tests/unit/test_loaders.py -v`
Expected: 5 passed.

- [ ] **Step 7: Commit**

```bash
git add src/autoagent/loaders tests/fixtures tests/unit/test_loaders.py
git commit -m "feat(loaders): JSONL/JSON/CSV batch file loaders"
```

---

## Task 12: Executor base interface

**Files:**
- Create: `src/autoagent/executors/__init__.py`
- Create: `src/autoagent/executors/base.py`
- Create: `tests/unit/test_executor_base.py`

- [ ] **Step 1: Write failing test `tests/unit/test_executor_base.py`**

```python
import asyncio
from typing import Any

import pytest

from autoagent.executors.base import Executor, ExecutorContext
from autoagent.models.api import Sample, SampleResult


class FakeExecutor(Executor):
    def __init__(self, *, flaky_for: int = 0):
        self.calls = 0
        self.flaky_for = flaky_for

    async def execute(self, sample: Sample, profile: Any, ctx: ExecutorContext) -> list[str]:
        self.calls += 1
        if self.calls <= self.flaky_for:
            raise RuntimeError("boom")
        return [f"reply to: {p}" for p in sample.prompts]


async def test_retry_and_success():
    ex = FakeExecutor(flaky_for=1)
    s = Sample(id="t1", prompts=["hello"], mode="api", target_profile="p", retry=2)
    result = await ex.run(s, profile=object(), default_timeout_sec=10)
    assert result.status == "done"
    assert result.attempt_count == 2
    assert result.responses == ["reply to: hello"]


async def test_all_retries_fail():
    ex = FakeExecutor(flaky_for=99)
    s = Sample(id="t1", prompts=["x"], mode="api", target_profile="p", retry=1)
    result = await ex.run(s, profile=object(), default_timeout_sec=10)
    assert result.status == "failed"
    assert result.attempt_count == 2
    assert "boom" in (result.error or "")


async def test_timeout_marks_timeout_status():
    class Slow(Executor):
        async def execute(self, *a, **k):
            await asyncio.sleep(10)
            return []
    s = Sample(id="t1", prompts=["x"], mode="api", target_profile="p", retry=0, timeout_sec=1)
    result = await Slow().run(s, profile=object(), default_timeout_sec=1)
    assert result.status == "timeout"


async def test_dry_run_returns_placeholder():
    ex = FakeExecutor()
    s = Sample(id="t1", prompts=["p1", "p2"], mode="api", target_profile="p", dry_run=True)
    result = await ex.run(s, profile=object(), default_timeout_sec=10)
    assert result.status == "done"
    assert all(r.startswith("[DRY RUN]") for r in result.responses)
```

- [ ] **Step 2: Write `src/autoagent/executors/base.py`**

```python
from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from autoagent.models.api import Sample, SampleResult


@dataclass
class ExecutorContext:
    logs_dir: str | None = None
    verbose_logs: bool = True


class Executor(ABC):
    """Base class. Subclasses implement `execute`. `run` is the supervised entry point."""

    @abstractmethod
    async def execute(self, sample: Sample, profile: Any, ctx: ExecutorContext) -> list[str]:
        """Run sample and return list of response strings (one per prompt). Raise on failure."""

    async def run(
        self,
        sample: Sample,
        profile: Any,
        default_timeout_sec: int,
        ctx: ExecutorContext | None = None,
    ) -> SampleResult:
        ctx = ctx or ExecutorContext()
        timeout_sec = sample.timeout_sec or default_timeout_sec
        attempts = 0
        max_attempts = sample.retry + 1
        last_error: str | None = None
        status: str = "failed"
        responses: list[str] = []
        started = datetime.now(timezone.utc)
        t0 = time.monotonic()

        if sample.dry_run:
            return SampleResult(
                id=sample.id,
                status="done",
                prompts_sent=list(sample.prompts),
                responses=[f"[DRY RUN] would send: {p}" for p in sample.prompts],
                duration_ms=int((time.monotonic() - t0) * 1000),
                attempt_count=1,
                mode=sample.mode,
                target_profile=sample.target_profile,
                metadata=dict(sample.metadata),
                logs_dir=ctx.logs_dir,
                started_at=started,
                ended_at=datetime.now(timezone.utc),
            )

        while attempts < max_attempts:
            attempts += 1
            try:
                responses = await asyncio.wait_for(
                    self.execute(sample, profile, ctx), timeout=timeout_sec
                )
                status = "done"
                last_error = None
                break
            except asyncio.TimeoutError:
                last_error = f"timeout after {timeout_sec}s"
                status = "timeout"
            except Exception as e:  # noqa: BLE001
                last_error = f"{type(e).__name__}: {e}"
                status = "failed"

        return SampleResult(
            id=sample.id,
            status=status if status == "done" else ("timeout" if status == "timeout" else "failed"),
            prompts_sent=list(sample.prompts),
            responses=responses,
            duration_ms=int((time.monotonic() - t0) * 1000),
            attempt_count=attempts,
            mode=sample.mode,
            target_profile=sample.target_profile,
            metadata=dict(sample.metadata),
            error=last_error,
            logs_dir=ctx.logs_dir,
            started_at=started,
            ended_at=datetime.now(timezone.utc),
        )
```

- [ ] **Step 3: Run tests, verify pass**

Run: `pytest tests/unit/test_executor_base.py -v`
Expected: 4 passed.

- [ ] **Step 4: Commit**

```bash
git add src/autoagent/executors/__init__.py src/autoagent/executors/base.py tests/unit/test_executor_base.py
git commit -m "feat(executors): base interface with retry, timeout, dry-run"
```

---

## Task 13: API Executor (OpenAI-compatible)

**Files:**
- Create: `src/autoagent/executors/api_executor.py`
- Create: `tests/unit/test_api_executor.py`

- [ ] **Step 1: Write failing test `tests/unit/test_api_executor.py`**

```python
import pytest
from pytest_httpx import HTTPXMock

from autoagent.executors.api_executor import ApiExecutor
from autoagent.executors.base import ExecutorContext
from autoagent.models.api import Sample
from autoagent.profiles.schemas import ApiProfile


def _make_profile(**kwargs) -> ApiProfile:
    base = {
        "name": "openai_gpt4",
        "platform": "api",
        "api": {
            "base_url": "https://api.example.com/v1",
            "model": "gpt-4o",
            "api_key_env": "OPENAI_TEST_KEY",
        },
    }
    base.update(kwargs)
    return ApiProfile.model_validate(base)


def _mock_chat_response(mock: HTTPXMock, content: str) -> None:
    mock.add_response(
        url="https://api.example.com/v1/chat/completions",
        json={
            "id": "cmpl-1",
            "object": "chat.completion",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    )


async def test_single_turn(monkeypatch, httpx_mock: HTTPXMock):
    monkeypatch.setenv("OPENAI_TEST_KEY", "sk-test")
    _mock_chat_response(httpx_mock, "hello there")
    sample = Sample(id="t1", prompts=["hi"], mode="api", target_profile="openai_gpt4")
    profile = _make_profile()
    result = await ApiExecutor().execute(sample, profile, ExecutorContext())
    assert result == ["hello there"]


async def test_multi_turn_history(monkeypatch, httpx_mock: HTTPXMock):
    monkeypatch.setenv("OPENAI_TEST_KEY", "sk-test")
    _mock_chat_response(httpx_mock, "r1")
    _mock_chat_response(httpx_mock, "r2")
    sample = Sample(id="t1", prompts=["p1", "p2"], mode="api", target_profile="openai_gpt4")
    profile = _make_profile(multi_turn_mode="history")
    result = await ApiExecutor().execute(sample, profile, ExecutorContext())
    assert result == ["r1", "r2"]

    # Second request must carry prior messages
    reqs = httpx_mock.get_requests()
    import json as _json
    body2 = _json.loads(reqs[1].content)
    assert len(body2["messages"]) >= 3  # user, assistant, user


async def test_multi_turn_single_resets_history(monkeypatch, httpx_mock: HTTPXMock):
    monkeypatch.setenv("OPENAI_TEST_KEY", "sk-test")
    _mock_chat_response(httpx_mock, "a")
    _mock_chat_response(httpx_mock, "b")
    sample = Sample(id="t1", prompts=["p1", "p2"], mode="api", target_profile="openai_gpt4")
    profile = _make_profile(multi_turn_mode="single")
    await ApiExecutor().execute(sample, profile, ExecutorContext())
    import json as _json
    req2 = httpx_mock.get_requests()[1]
    body2 = _json.loads(req2.content)
    assert len(body2["messages"]) == 1


async def test_missing_api_key_env_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_TEST_KEY", raising=False)
    sample = Sample(id="t1", prompts=["hi"], mode="api", target_profile="openai_gpt4")
    with pytest.raises(RuntimeError, match="env var OPENAI_TEST_KEY"):
        await ApiExecutor().execute(sample, _make_profile(), ExecutorContext())
```

- [ ] **Step 2: Write `src/autoagent/executors/api_executor.py`**

```python
from __future__ import annotations

import os
from typing import Any

import httpx

from autoagent.executors.base import Executor, ExecutorContext
from autoagent.models.api import Sample
from autoagent.profiles.schemas import ApiProfile


class ApiExecutor(Executor):
    """Calls any OpenAI-compatible /v1/chat/completions endpoint."""

    async def execute(self, sample: Sample, profile: Any, ctx: ExecutorContext) -> list[str]:
        if not isinstance(profile, ApiProfile):
            raise TypeError(f"ApiExecutor expects ApiProfile, got {type(profile).__name__}")

        api_key = os.getenv(profile.api.api_key_env)
        if not api_key:
            raise RuntimeError(f"env var {profile.api.api_key_env} is not set")

        url = profile.api.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            **profile.api.extra_headers,
        }

        messages: list[dict[str, str]] = []
        responses: list[str] = []

        async with httpx.AsyncClient(timeout=httpx.Timeout(None)) as client:
            for prompt in sample.prompts:
                if profile.multi_turn_mode == "history":
                    messages.append({"role": "user", "content": prompt})
                else:
                    messages = [{"role": "user", "content": prompt}]

                payload: dict[str, Any] = {"model": profile.api.model, "messages": messages}
                if profile.api.temperature is not None:
                    payload["temperature"] = profile.api.temperature
                if profile.api.max_tokens is not None:
                    payload["max_tokens"] = profile.api.max_tokens

                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                try:
                    text = data["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError) as e:
                    raise RuntimeError(f"unexpected response shape: {data}") from e

                responses.append(text)
                if profile.multi_turn_mode == "history":
                    messages.append({"role": "assistant", "content": text})

        return responses
```

- [ ] **Step 3: Run tests, verify pass**

Run: `pytest tests/unit/test_api_executor.py -v`
Expected: 4 passed.

- [ ] **Step 4: Commit**

```bash
git add src/autoagent/executors/api_executor.py tests/unit/test_api_executor.py
git commit -m "feat(executors): OpenAI-compatible API executor with multi-turn"
```

---

## Task 14: Result writer (JSONL per batch)

**Files:**
- Create: `src/autoagent/results/__init__.py`
- Create: `src/autoagent/results/writer.py`
- Create: `tests/unit/test_result_writer.py`

- [ ] **Step 1: Write failing tests `tests/unit/test_result_writer.py`**

```python
import json
from pathlib import Path

from autoagent.config.settings import get_settings
from autoagent.models.api import SampleResult
from autoagent.results.writer import ResultWriter


def _res(sid: str, status: str = "done") -> SampleResult:
    return SampleResult(
        id=sid, status=status, prompts_sent=["p"], responses=["r"],
        duration_ms=10, attempt_count=1, mode="api", target_profile="pf",
    )


def test_writes_jsonl_in_order():
    w = ResultWriter("b1")
    w.append(_res("t1"))
    w.append(_res("t2", "failed"))
    w.close()
    path = get_settings().data_root / "results" / "b1.jsonl"
    assert path.exists()
    lines = path.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["id"] == "t1"
    assert json.loads(lines[1])["status"] == "failed"


def test_reopen_appends():
    w = ResultWriter("b2")
    w.append(_res("t1"))
    w.close()
    w2 = ResultWriter("b2")
    w2.append(_res("t2"))
    w2.close()
    path = get_settings().data_root / "results" / "b2.jsonl"
    lines = path.read_text().splitlines()
    assert len(lines) == 2
```

- [ ] **Step 2: Write `src/autoagent/results/writer.py`**

```python
from __future__ import annotations

import json
import threading
from pathlib import Path

from autoagent.config.settings import get_settings
from autoagent.models.api import SampleResult


class ResultWriter:
    def __init__(self, batch_id: str):
        root = get_settings().data_root / "results"
        root.mkdir(parents=True, exist_ok=True)
        self.path: Path = root / f"{batch_id}.jsonl"
        self._fh = self.path.open("a", encoding="utf-8")
        self._lock = threading.Lock()

    def append(self, result: SampleResult) -> None:
        with self._lock:
            self._fh.write(result.model_dump_json() + "\n")
            self._fh.flush()

    def close(self) -> None:
        with self._lock:
            if not self._fh.closed:
                self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
```

- [ ] **Step 3: Run tests, verify pass**

Run: `pytest tests/unit/test_result_writer.py -v`
Expected: 2 passed.

- [ ] **Step 4: Commit**

```bash
git add src/autoagent/results/__init__.py src/autoagent/results/writer.py tests/unit/test_result_writer.py
git commit -m "feat(results): JSONL per-batch result writer (thread-safe)"
```

---

## Task 15: Batch + sample storage CRUD

**Files:**
- Create: `src/autoagent/storage/batches.py`
- Create: `src/autoagent/storage/samples.py`
- Create: `tests/unit/test_batch_storage.py`

- [ ] **Step 1: Write failing tests `tests/unit/test_batch_storage.py`**

```python
import pytest

from autoagent.storage.database import init_db
from autoagent.storage.batches import create_batch, get_batch, list_batches, update_batch_status, update_batch_progress
from autoagent.storage.samples import upsert_sample, list_samples_for_batch
from autoagent.models.api import Sample, SampleResult


async def test_batch_create_and_get():
    await init_db()
    await create_batch(batch_id="b1", name="test", mode="api", concurrency=2, total=3, target_profile_default=None)
    b = await get_batch("b1")
    assert b is not None
    assert b.name == "test"
    assert b.total == 3
    assert b.status == "queued"


async def test_batch_list_orders_newest_first():
    await init_db()
    await create_batch(batch_id="b1", name="n1", mode="api", concurrency=1, total=1, target_profile_default=None)
    await create_batch(batch_id="b2", name="n2", mode="api", concurrency=1, total=1, target_profile_default=None)
    batches = await list_batches(limit=10, offset=0)
    assert batches[0].id == "b2"


async def test_sample_upsert_and_list():
    await init_db()
    await create_batch(batch_id="b1", name="t", mode="api", concurrency=1, total=2, target_profile_default=None)
    r = SampleResult(id="t1", status="done", prompts_sent=["p"], responses=["r"], duration_ms=10, attempt_count=1, mode="api", target_profile="pf")
    await upsert_sample("b1", r)
    rs = await list_samples_for_batch("b1")
    assert len(rs) == 1
    assert rs[0].id == "t1"
    assert rs[0].status == "done"


async def test_update_progress():
    await init_db()
    await create_batch(batch_id="b1", name="t", mode="api", concurrency=1, total=10, target_profile_default=None)
    await update_batch_progress("b1", done=5, failed=1, avg_duration_ms=100, total_duration_ms=500)
    b = await get_batch("b1")
    assert b.done == 5
    assert b.failed == 1
```

- [ ] **Step 2: Write `src/autoagent/storage/batches.py`**

```python
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import desc, select

from autoagent.models.db import Batch
from autoagent.storage.database import get_sessionmaker


async def create_batch(
    *, batch_id: str, name: str, mode: str, concurrency: int, total: int,
    target_profile_default: str | None,
) -> None:
    sm = get_sessionmaker()
    async with sm() as s:
        s.add(Batch(
            id=batch_id, name=name, mode=mode, concurrency=concurrency,
            total=total, target_profile_default=target_profile_default, status="queued",
        ))
        await s.commit()


async def get_batch(batch_id: str) -> Batch | None:
    sm = get_sessionmaker()
    async with sm() as s:
        return await s.get(Batch, batch_id)


async def list_batches(limit: int = 50, offset: int = 0) -> list[Batch]:
    sm = get_sessionmaker()
    async with sm() as s:
        result = await s.execute(
            select(Batch).order_by(desc(Batch.created_at)).limit(limit).offset(offset)
        )
        return list(result.scalars().all())


async def update_batch_status(batch_id: str, status: str) -> None:
    sm = get_sessionmaker()
    async with sm() as s:
        b = await s.get(Batch, batch_id)
        if b is None:
            return
        b.status = status
        if status == "running" and b.started_at is None:
            b.started_at = datetime.now(timezone.utc)
        if status in ("done", "failed", "cancelled"):
            b.ended_at = datetime.now(timezone.utc)
        await s.commit()


async def update_batch_progress(
    batch_id: str, *, done: int, failed: int,
    avg_duration_ms: int | None = None, total_duration_ms: int | None = None,
) -> None:
    sm = get_sessionmaker()
    async with sm() as s:
        b = await s.get(Batch, batch_id)
        if b is None:
            return
        b.done = done
        b.failed = failed
        if avg_duration_ms is not None:
            b.avg_duration_ms = avg_duration_ms
        if total_duration_ms is not None:
            b.total_duration_ms = total_duration_ms
        await s.commit()
```

- [ ] **Step 3: Write `src/autoagent/storage/samples.py`**

```python
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select

from autoagent.models.db import Sample as SampleRow
from autoagent.models.api import SampleResult
from autoagent.storage.database import get_sessionmaker


def _row_to_result(r: SampleRow) -> SampleResult:
    return SampleResult(
        id=r.id,
        status=r.status,  # type: ignore[arg-type]
        prompts_sent=json.loads(r.prompts_sent_json or "[]"),
        responses=json.loads(r.responses_json or "[]"),
        duration_ms=r.duration_ms,
        attempt_count=r.attempt_count,
        mode=r.mode,  # type: ignore[arg-type]
        target_profile=r.target_profile,
        metadata=json.loads(r.metadata_json or "{}"),
        error=r.error,
        logs_dir=r.logs_dir,
        started_at=r.started_at.replace(tzinfo=timezone.utc) if r.started_at else None,
        ended_at=r.ended_at.replace(tzinfo=timezone.utc) if r.ended_at else None,
    )


async def upsert_sample(batch_id: str, result: SampleResult) -> None:
    sm = get_sessionmaker()
    async with sm() as s:
        existing = await s.get(SampleRow, (batch_id, result.id))
        if existing is None:
            existing = SampleRow(batch_id=batch_id, id=result.id, mode=result.mode, target_profile=result.target_profile)
            s.add(existing)
        existing.status = result.status
        existing.prompts_sent_json = json.dumps(result.prompts_sent)
        existing.responses_json = json.dumps(result.responses, ensure_ascii=False)
        existing.duration_ms = result.duration_ms
        existing.attempt_count = result.attempt_count
        existing.mode = result.mode
        existing.target_profile = result.target_profile
        existing.metadata_json = json.dumps(result.metadata, ensure_ascii=False)
        existing.error = result.error
        existing.logs_dir = result.logs_dir
        existing.started_at = result.started_at
        existing.ended_at = result.ended_at
        await s.commit()


async def list_samples_for_batch(batch_id: str) -> list[SampleResult]:
    sm = get_sessionmaker()
    async with sm() as s:
        r = await s.execute(select(SampleRow).where(SampleRow.batch_id == batch_id))
        return [_row_to_result(row) for row in r.scalars().all()]
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/unit/test_batch_storage.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/autoagent/storage/batches.py src/autoagent/storage/samples.py tests/unit/test_batch_storage.py
git commit -m "feat(storage): batch and sample CRUD"
```

---

## Task 16: Config storage (VLM + defaults key-value)

**Files:**
- Create: `src/autoagent/storage/configs.py`
- Create: `tests/unit/test_configs_storage.py`

- [ ] **Step 1: Write failing tests `tests/unit/test_configs_storage.py`**

```python
from autoagent.storage.configs import get_config, put_config
from autoagent.storage.database import init_db


async def test_config_roundtrip():
    await init_db()
    await put_config("vlm", {"base_url": "http://x", "model": "m", "api_key_env": "K"})
    v = await get_config("vlm")
    assert v == {"base_url": "http://x", "model": "m", "api_key_env": "K"}


async def test_get_missing_returns_none():
    await init_db()
    assert await get_config("nope") is None
```

- [ ] **Step 2: Write `src/autoagent/storage/configs.py`**

```python
from __future__ import annotations

import json
from typing import Any

from autoagent.models.db import ConfigKV
from autoagent.storage.database import get_sessionmaker


async def get_config(key: str) -> Any | None:
    sm = get_sessionmaker()
    async with sm() as s:
        row = await s.get(ConfigKV, key)
        return json.loads(row.value_json) if row else None


async def put_config(key: str, value: Any) -> None:
    sm = get_sessionmaker()
    async with sm() as s:
        row = await s.get(ConfigKV, key)
        if row is None:
            s.add(ConfigKV(key=key, value_json=json.dumps(value, ensure_ascii=False)))
        else:
            row.value_json = json.dumps(value, ensure_ascii=False)
        await s.commit()
```

- [ ] **Step 3: Run tests, verify pass**

Run: `pytest tests/unit/test_configs_storage.py -v`
Expected: 2 passed.

- [ ] **Step 4: Commit**

```bash
git add src/autoagent/storage/configs.py tests/unit/test_configs_storage.py
git commit -m "feat(storage): key-value config store"
```

---

## Task 17: Webhook sender

**Files:**
- Create: `src/autoagent/webhooks/__init__.py`
- Create: `src/autoagent/webhooks/sender.py`
- Create: `tests/unit/test_webhooks.py`

- [ ] **Step 1: Write failing test `tests/unit/test_webhooks.py`**

```python
from pytest_httpx import HTTPXMock

from autoagent.models.api import SampleResult
from autoagent.webhooks.sender import send_webhook


def _res() -> SampleResult:
    return SampleResult(
        id="t1", status="done", prompts_sent=["p"], responses=["r"],
        duration_ms=10, attempt_count=1, mode="api", target_profile="pf",
    )


async def test_send_success(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url="http://example.com/cb", status_code=200)
    ok = await send_webhook("http://example.com/cb", _res())
    assert ok is True


async def test_send_retries_on_500(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url="http://example.com/cb", status_code=500)
    httpx_mock.add_response(url="http://example.com/cb", status_code=500)
    httpx_mock.add_response(url="http://example.com/cb", status_code=200)
    ok = await send_webhook("http://example.com/cb", _res(), max_retries=3, base_delay=0.01)
    assert ok is True
    assert len(httpx_mock.get_requests()) == 3


async def test_send_eventually_gives_up(httpx_mock: HTTPXMock):
    for _ in range(3):
        httpx_mock.add_response(url="http://example.com/cb", status_code=500)
    ok = await send_webhook("http://example.com/cb", _res(), max_retries=3, base_delay=0.01)
    assert ok is False
```

- [ ] **Step 2: Write `src/autoagent/webhooks/sender.py`**

```python
from __future__ import annotations

import asyncio
import logging

import httpx

from autoagent.models.api import SampleResult

log = logging.getLogger(__name__)


async def send_webhook(
    url: str, result: SampleResult, *, max_retries: int = 3, base_delay: float = 0.5,
) -> bool:
    delay = base_delay
    async with httpx.AsyncClient(timeout=10) as client:
        for attempt in range(1, max_retries + 1):
            try:
                resp = await client.post(
                    url,
                    json=result.model_dump(mode="json"),
                    headers={"Content-Type": "application/json"},
                )
                if 200 <= resp.status_code < 300:
                    return True
                log.warning("webhook %s returned %s (attempt %d)", url, resp.status_code, attempt)
            except httpx.RequestError as e:
                log.warning("webhook %s error: %s (attempt %d)", url, e, attempt)
            if attempt < max_retries:
                await asyncio.sleep(delay)
                delay *= 2
    return False
```

- [ ] **Step 3: Run tests, verify pass**

Run: `pytest tests/unit/test_webhooks.py -v`
Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
git add src/autoagent/webhooks tests/unit/test_webhooks.py
git commit -m "feat(webhooks): async webhook sender with exponential backoff"
```

---

## Task 18: Batch scheduler

**Files:**
- Create: `src/autoagent/scheduler/__init__.py`
- Create: `src/autoagent/scheduler/batch_scheduler.py`
- Create: `tests/unit/test_scheduler.py`

- [ ] **Step 1: Write failing tests `tests/unit/test_scheduler.py`**

```python
import asyncio

import pytest

from autoagent.models.api import Sample
from autoagent.scheduler.batch_scheduler import BatchScheduler
from autoagent.storage.database import init_db
from autoagent.storage.batches import get_batch
from autoagent.storage.samples import list_samples_for_batch
from autoagent.executors.base import Executor, ExecutorContext


class EchoExec(Executor):
    def __init__(self, delay: float = 0):
        self.delay = delay

    async def execute(self, sample, profile, ctx: ExecutorContext) -> list[str]:
        if self.delay:
            await asyncio.sleep(self.delay)
        return [f"echo:{p}" for p in sample.prompts]


@pytest.fixture
async def scheduler(monkeypatch):
    await init_db()
    sch = BatchScheduler(executor_factory=lambda mode: EchoExec(), profile_lookup=lambda name: object())
    yield sch


async def test_run_batch_completes_all(scheduler):
    samples = [Sample(id=f"t{i}", prompts=["x"], mode="api", target_profile="p") for i in range(3)]
    batch_id = await scheduler.submit(name="b", mode="api", concurrency=2, samples=samples)
    await scheduler.wait_done(batch_id, timeout_sec=5)
    b = await get_batch(batch_id)
    assert b.status == "done"
    assert b.done == 3
    assert b.failed == 0
    results = await list_samples_for_batch(batch_id)
    assert len(results) == 3
    assert all(r.status == "done" for r in results)


async def test_concurrency_limits_parallelism():
    # Executor that tracks concurrent running count
    import itertools
    current = itertools.count()
    max_seen = [0]
    now_running = [0]

    class Tracker(Executor):
        async def execute(self, sample, profile, ctx):
            now_running[0] += 1
            max_seen[0] = max(max_seen[0], now_running[0])
            await asyncio.sleep(0.05)
            now_running[0] -= 1
            return ["ok"]

    await init_db()
    sch = BatchScheduler(executor_factory=lambda mode: Tracker(), profile_lookup=lambda n: object())
    samples = [Sample(id=f"t{i}", prompts=["x"], mode="api", target_profile="p") for i in range(6)]
    batch_id = await sch.submit(name="b", mode="api", concurrency=2, samples=samples)
    await sch.wait_done(batch_id, timeout_sec=5)
    assert max_seen[0] <= 2
```

- [ ] **Step 2: Write `src/autoagent/scheduler/batch_scheduler.py`**

```python
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from autoagent.config.settings import get_settings
from autoagent.executors.base import Executor, ExecutorContext
from autoagent.models.api import Mode, Sample, SampleResult
from autoagent.results.writer import ResultWriter
from autoagent.storage.batches import (
    create_batch,
    update_batch_progress,
    update_batch_status,
)
from autoagent.storage.samples import upsert_sample
from autoagent.webhooks.sender import send_webhook

log = logging.getLogger(__name__)


@dataclass
class _RunState:
    samples: list[Sample]
    mode: Mode
    concurrency: int
    target_profile_default: str | None
    done_event: asyncio.Event = field(default_factory=asyncio.Event)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    done_count: int = 0
    failed_count: int = 0
    total_duration_ms: int = 0
    results: list[SampleResult] = field(default_factory=list)


class BatchScheduler:
    def __init__(
        self,
        executor_factory: Callable[[str], Executor],
        profile_lookup: Callable[[str], Any],
    ):
        self._executor_factory = executor_factory
        self._profile_lookup = profile_lookup
        self._states: dict[str, _RunState] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    async def submit(
        self, *, name: str, mode: Mode, concurrency: int, samples: list[Sample],
        target_profile_default: str | None = None,
    ) -> str:
        batch_id = f"b_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        state = _RunState(
            samples=samples, mode=mode, concurrency=max(1, concurrency),
            target_profile_default=target_profile_default,
        )
        self._states[batch_id] = state
        await create_batch(
            batch_id=batch_id, name=name, mode=mode, concurrency=state.concurrency,
            total=len(samples), target_profile_default=target_profile_default,
        )
        self._tasks[batch_id] = asyncio.create_task(self._run(batch_id, state))
        return batch_id

    async def cancel(self, batch_id: str) -> bool:
        state = self._states.get(batch_id)
        if state is None:
            return False
        state.cancel_event.set()
        return True

    async def wait_done(self, batch_id: str, timeout_sec: float | None = None) -> None:
        state = self._states.get(batch_id)
        if state is None:
            return
        await asyncio.wait_for(state.done_event.wait(), timeout=timeout_sec)

    def get_results(self, batch_id: str) -> list[SampleResult]:
        state = self._states.get(batch_id)
        return list(state.results) if state else []

    async def _run(self, batch_id: str, state: _RunState) -> None:
        settings = get_settings()
        await update_batch_status(batch_id, "running")
        writer = ResultWriter(batch_id)
        sem = asyncio.Semaphore(state.concurrency)
        start = time.monotonic()

        async def run_one(sample: Sample) -> None:
            async with sem:
                if state.cancel_event.is_set():
                    result = SampleResult(
                        id=sample.id, status="cancelled", prompts_sent=list(sample.prompts),
                        mode=sample.mode, target_profile=sample.target_profile,
                    )
                else:
                    # Resolve profile
                    try:
                        profile = self._profile_lookup(sample.target_profile)
                    except Exception as e:
                        result = SampleResult(
                            id=sample.id, status="failed", prompts_sent=list(sample.prompts),
                            mode=sample.mode, target_profile=sample.target_profile,
                            error=f"profile lookup failed: {e}",
                        )
                    else:
                        default_timeout = (
                            settings.default_api_timeout_sec if sample.mode == "api"
                            else settings.default_gui_timeout_sec
                        )
                        ctx = ExecutorContext(verbose_logs=settings.default_verbose_logs)
                        executor = self._executor_factory(sample.mode)
                        result = await executor.run(
                            sample, profile=profile, default_timeout_sec=default_timeout, ctx=ctx,
                        )

                writer.append(result)
                try:
                    await upsert_sample(batch_id, result)
                except Exception:
                    log.exception("failed to persist sample %s", sample.id)

                state.results.append(result)
                if result.status == "done":
                    state.done_count += 1
                else:
                    state.failed_count += 1
                if result.duration_ms:
                    state.total_duration_ms += result.duration_ms

                try:
                    await update_batch_progress(
                        batch_id, done=state.done_count, failed=state.failed_count,
                        total_duration_ms=state.total_duration_ms,
                        avg_duration_ms=(
                            state.total_duration_ms
                            // max(1, state.done_count + state.failed_count)
                        ),
                    )
                except Exception:
                    log.exception("failed to update batch progress")

                if sample.callback_url:
                    try:
                        await send_webhook(sample.callback_url, result)
                    except Exception:
                        log.exception("webhook failed for %s", sample.id)

        try:
            await asyncio.gather(*(run_one(s) for s in state.samples))
            final_status = (
                "cancelled" if state.cancel_event.is_set()
                else ("done" if state.failed_count == 0 else "failed")
            )
            await update_batch_status(batch_id, final_status)
        finally:
            writer.close()
            state.done_event.set()
            log.info("batch %s complete in %.1fs", batch_id, time.monotonic() - start)
```

- [ ] **Step 3: Run tests, verify pass**

Run: `pytest tests/unit/test_scheduler.py -v`
Expected: 2 passed.

- [ ] **Step 4: Commit**

```bash
git add src/autoagent/scheduler tests/unit/test_scheduler.py
git commit -m "feat(scheduler): async batch scheduler with concurrency and persistence"
```

---

## Task 19: Single-test endpoints (sync + async)

**Files:**
- Create: `src/autoagent/api/tests.py`
- Modify: `src/autoagent/main.py`
- Create: `tests/integration/test_tests_endpoints.py`

- [ ] **Step 1: Write `src/autoagent/api/tests.py`**

```python
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException

from autoagent.api._deps import get_scheduler
from autoagent.auth.deps import require_user
from autoagent.models.api import AsyncTestResponse, Sample, SampleResult
from autoagent.storage.samples import list_samples_for_batch

log = logging.getLogger(__name__)

router = APIRouter(prefix="/tests", tags=["tests"], dependencies=[Depends(require_user)])


@router.post("/sync", response_model=SampleResult)
async def run_sync(sample: Sample) -> SampleResult:
    sch = get_scheduler()
    batch_id = await sch.submit(
        name=f"sync-{sample.id}", mode=sample.mode, concurrency=1, samples=[sample],
    )
    await sch.wait_done(batch_id, timeout_sec=(sample.timeout_sec or 600) + 30)
    results = await list_samples_for_batch(batch_id)
    if not results:
        raise HTTPException(status_code=500, detail="no result recorded")
    return results[0]


@router.post("", response_model=AsyncTestResponse, status_code=202)
async def run_async(sample: Sample) -> AsyncTestResponse:
    sch = get_scheduler()
    batch_id = await sch.submit(
        name=f"async-{sample.id}", mode=sample.mode, concurrency=1, samples=[sample],
    )
    return AsyncTestResponse(task_id=batch_id)


@router.get("/{task_id}", response_model=SampleResult)
async def get_async_result(task_id: str) -> SampleResult:
    results = await list_samples_for_batch(task_id)
    if not results:
        # Still running or unknown; return synthetic running placeholder
        raise HTTPException(status_code=404, detail="task not found or no result yet")
    return results[0]
```

- [ ] **Step 2: Create `src/autoagent/api/_deps.py` (scheduler singleton holder)**

```python
from __future__ import annotations

from typing import Any

from autoagent.executors.api_executor import ApiExecutor
from autoagent.executors.base import Executor
from autoagent.profiles.registry import load_profile
from autoagent.scheduler.batch_scheduler import BatchScheduler

_scheduler: BatchScheduler | None = None


def _build_executor(mode: str) -> Executor:
    if mode == "api":
        return ApiExecutor()
    raise ValueError(f"mode {mode} not supported in this build (see later plans for web/android)")


def _lookup_profile(name: str) -> Any:
    p = load_profile(name)
    if p is None:
        raise LookupError(f"profile {name!r} not found")
    return p


def get_scheduler() -> BatchScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BatchScheduler(executor_factory=_build_executor, profile_lookup=_lookup_profile)
    return _scheduler


def reset_scheduler_for_tests() -> None:
    global _scheduler
    _scheduler = None
```

- [ ] **Step 3: Update `src/autoagent/main.py`**

```python
from fastapi import FastAPI

from autoagent.api.auth import router as auth_router
from autoagent.api.profiles import router as profiles_router
from autoagent.api.tests import router as tests_router

app = FastAPI(title="AutoAgent Test", version="0.1.0")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(profiles_router, prefix="/api/v1")
app.include_router(tests_router, prefix="/api/v1")
```

- [ ] **Step 4: Extend `tests/conftest.py` to reset scheduler**

Append to `tests/conftest.py`:

```python
@pytest.fixture(autouse=True)
def _reset_scheduler():
    yield
    from autoagent.api._deps import reset_scheduler_for_tests
    reset_scheduler_for_tests()
```

- [ ] **Step 5: Write `tests/integration/test_tests_endpoints.py`**

```python
import pytest
import yaml
from httpx import ASGITransport, AsyncClient
from pytest_httpx import HTTPXMock

from autoagent.auth.passwords import hash_password
from autoagent.profiles.registry import save_profile_yaml
from autoagent.storage.database import init_db
from autoagent.storage.users import upsert_user


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setenv("OPENAI_TEST_KEY", "sk-test")
    await init_db()
    await upsert_user("admin", hash_password("pw"))
    save_profile_yaml("p_api", yaml.safe_dump({
        "name": "p_api", "platform": "api",
        "api": {"base_url": "https://api.example.com/v1", "model": "m", "api_key_env": "OPENAI_TEST_KEY"},
    }))
    from autoagent.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _login(client) -> dict:
    r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def test_sync_test_runs_to_done(client, httpx_mock: HTTPXMock, monkeypatch):
    httpx_mock.add_response(
        url="https://api.example.com/v1/chat/completions",
        json={"choices": [{"message": {"content": "hi!"}}]},
    )
    h = await _login(client)
    sample = {"id": "t1", "prompts": ["yo"], "mode": "api", "target_profile": "p_api"}
    r = await client.post("/api/v1/tests/sync", json=sample, headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "done"
    assert body["responses"] == ["hi!"]


async def test_async_test_lifecycle(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url="https://api.example.com/v1/chat/completions",
        json={"choices": [{"message": {"content": "async ok"}}]},
    )
    h = await _login(client)
    sample = {"id": "t1", "prompts": ["yo"], "mode": "api", "target_profile": "p_api"}
    r = await client.post("/api/v1/tests", json=sample, headers=h)
    assert r.status_code == 202
    task_id = r.json()["task_id"]

    import asyncio
    for _ in range(40):
        await asyncio.sleep(0.1)
        r = await client.get(f"/api/v1/tests/{task_id}", headers=h)
        if r.status_code == 200 and r.json()["status"] in ("done", "failed"):
            break
    assert r.json()["status"] == "done"
    assert r.json()["responses"] == ["async ok"]
```

- [ ] **Step 6: Run tests, verify pass**

Run: `pytest tests/integration/test_tests_endpoints.py -v`
Expected: 2 passed.

- [ ] **Step 7: Commit**

```bash
git add src/autoagent/api/tests.py src/autoagent/api/_deps.py src/autoagent/main.py tests/conftest.py tests/integration/test_tests_endpoints.py
git commit -m "feat(api): sync + async single-test endpoints"
```

---

## Task 20: Batch endpoints

**Files:**
- Create: `src/autoagent/api/batches.py`
- Modify: `src/autoagent/main.py`
- Create: `tests/integration/test_batches_endpoints.py`

- [ ] **Step 1: Write `src/autoagent/api/batches.py`**

```python
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from autoagent.api._deps import get_scheduler
from autoagent.auth.deps import require_user
from autoagent.config.settings import get_settings
from autoagent.loaders.csv_loader import load_csv
from autoagent.loaders.json_loader import load_json
from autoagent.loaders.jsonl_loader import load_jsonl
from autoagent.models.api import (
    BatchCreatedResponse, BatchCreateJSON, BatchDetail, BatchSummary, Mode,
)
from autoagent.storage.batches import get_batch, list_batches
from autoagent.storage.samples import list_samples_for_batch

router = APIRouter(prefix="/batches", tags=["batches"], dependencies=[Depends(require_user)])


def _parse_file(filename: str, text: str):
    ext = Path(filename).suffix.lower()
    if ext == ".jsonl":
        return load_jsonl(text)
    if ext == ".json":
        return load_json(text)
    if ext == ".csv":
        return load_csv(text)
    raise HTTPException(status_code=400, detail=f"unsupported extension {ext}")


def _apply_default_profile(samples, default_profile: str | None):
    if default_profile is None:
        return
    for s in samples:
        if not s.target_profile:
            s.target_profile = default_profile


@router.post("", response_model=BatchCreatedResponse, status_code=201)
async def create_batch_json(body: BatchCreateJSON) -> BatchCreatedResponse:
    _apply_default_profile(body.samples, body.target_profile_default)
    sch = get_scheduler()
    batch_id = await sch.submit(
        name=body.name, mode=body.mode, concurrency=body.concurrency, samples=body.samples,
        target_profile_default=body.target_profile_default,
    )
    return BatchCreatedResponse(batch_id=batch_id)


@router.post("/upload", response_model=BatchCreatedResponse, status_code=201)
async def create_batch_file(
    name: str = Form(...),
    mode: str = Form(...),
    concurrency: int = Form(1),
    target_profile_default: str | None = Form(None),
    file: UploadFile = File(...),
) -> BatchCreatedResponse:
    text = (await file.read()).decode("utf-8")
    samples = _parse_file(file.filename or "batch.jsonl", text)
    _apply_default_profile(samples, target_profile_default)
    # Validate all modes match
    for s in samples:
        if s.mode != mode:
            raise HTTPException(status_code=400, detail=f"sample {s.id} mode={s.mode} != batch mode={mode}")
    sch = get_scheduler()
    batch_id = await sch.submit(
        name=name, mode=mode, concurrency=concurrency, samples=samples,
        target_profile_default=target_profile_default,
    )
    return BatchCreatedResponse(batch_id=batch_id)


@router.get("", response_model=list[BatchSummary])
async def list_all(limit: int = 50, offset: int = 0) -> list[BatchSummary]:
    rows = await list_batches(limit=limit, offset=offset)
    return [
        BatchSummary(
            batch_id=r.id, name=r.name, mode=r.mode, status=r.status,
            total=r.total, done=r.done, failed=r.failed,
            avg_duration_ms=r.avg_duration_ms, total_duration_ms=r.total_duration_ms,
            started_at=r.started_at, ended_at=r.ended_at,
        ) for r in rows
    ]


@router.get("/{batch_id}", response_model=BatchDetail)
async def get_one(batch_id: str) -> BatchDetail:
    b = await get_batch(batch_id)
    if b is None:
        raise HTTPException(status_code=404, detail="batch not found")
    samples = await list_samples_for_batch(batch_id)
    return BatchDetail(
        batch_id=b.id, name=b.name, mode=b.mode, status=b.status,
        total=b.total, done=b.done, failed=b.failed,
        avg_duration_ms=b.avg_duration_ms, total_duration_ms=b.total_duration_ms,
        started_at=b.started_at, ended_at=b.ended_at,
        samples=samples,
    )


@router.get("/{batch_id}/results")
async def download_results(batch_id: str) -> FileResponse:
    path = get_settings().data_root / "results" / f"{batch_id}.jsonl"
    if not path.exists():
        raise HTTPException(status_code=404, detail="results file not found")
    return FileResponse(path, media_type="application/x-ndjson", filename=f"{batch_id}.jsonl")


@router.post("/{batch_id}/cancel", status_code=202)
async def cancel(batch_id: str) -> dict:
    sch = get_scheduler()
    ok = await sch.cancel(batch_id)
    if not ok:
        raise HTTPException(status_code=404, detail="batch not found or already finished")
    return {"batch_id": batch_id, "status": "cancelling"}
```

- [ ] **Step 2: Update `src/autoagent/main.py`**

```python
from fastapi import FastAPI

from autoagent.api.auth import router as auth_router
from autoagent.api.batches import router as batches_router
from autoagent.api.profiles import router as profiles_router
from autoagent.api.tests import router as tests_router

app = FastAPI(title="AutoAgent Test", version="0.1.0")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(profiles_router, prefix="/api/v1")
app.include_router(tests_router, prefix="/api/v1")
app.include_router(batches_router, prefix="/api/v1")
```

- [ ] **Step 3: Write `tests/integration/test_batches_endpoints.py`**

```python
import asyncio
import pytest
import yaml
from httpx import ASGITransport, AsyncClient
from pytest_httpx import HTTPXMock

from autoagent.auth.passwords import hash_password
from autoagent.profiles.registry import save_profile_yaml
from autoagent.storage.database import init_db
from autoagent.storage.users import upsert_user


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setenv("OPENAI_TEST_KEY", "sk-test")
    await init_db()
    await upsert_user("admin", hash_password("pw"))
    save_profile_yaml("p_api", yaml.safe_dump({
        "name": "p_api", "platform": "api",
        "api": {"base_url": "https://api.example.com/v1", "model": "m", "api_key_env": "OPENAI_TEST_KEY"},
    }))
    from autoagent.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _login(client) -> dict:
    r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def _wait_done(client, h, batch_id, n=40):
    for _ in range(n):
        await asyncio.sleep(0.1)
        r = await client.get(f"/api/v1/batches/{batch_id}", headers=h)
        if r.json()["status"] in ("done", "failed", "cancelled"):
            return r.json()
    raise AssertionError("batch did not finish in time")


async def test_json_batch_flow(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(url="https://api.example.com/v1/chat/completions", json={"choices": [{"message": {"content": "a"}}]})
    httpx_mock.add_response(url="https://api.example.com/v1/chat/completions", json={"choices": [{"message": {"content": "b"}}]})
    h = await _login(client)

    body = {
        "name": "batch1", "mode": "api", "concurrency": 1,
        "samples": [
            {"id": "t1", "prompts": ["x"], "mode": "api", "target_profile": "p_api"},
            {"id": "t2", "prompts": ["y"], "mode": "api", "target_profile": "p_api"},
        ],
    }
    r = await client.post("/api/v1/batches", json=body, headers=h)
    assert r.status_code == 201
    batch_id = r.json()["batch_id"]

    final = await _wait_done(client, h, batch_id)
    assert final["done"] == 2 and final["failed"] == 0
    assert final["status"] == "done"

    r = await client.get(f"/api/v1/batches/{batch_id}/results", headers=h)
    assert r.status_code == 200
    lines = r.text.strip().splitlines()
    assert len(lines) == 2


async def test_file_upload_batch(client, httpx_mock: HTTPXMock, tmp_path):
    httpx_mock.add_response(url="https://api.example.com/v1/chat/completions", json={"choices": [{"message": {"content": "ok"}}]})
    h = await _login(client)
    jsonl = '{"id":"t1","prompts":["a"],"mode":"api","target_profile":"p_api"}\n'
    files = {"file": ("b.jsonl", jsonl, "application/x-ndjson")}
    data = {"name": "upl", "mode": "api", "concurrency": "1"}
    r = await client.post("/api/v1/batches/upload", files=files, data=data, headers=h)
    assert r.status_code == 201
    batch_id = r.json()["batch_id"]
    final = await _wait_done(client, h, batch_id)
    assert final["done"] == 1


async def test_mode_mismatch_rejected(client):
    h = await _login(client)
    body = {
        "name": "x", "mode": "api", "concurrency": 1,
        "samples": [{"id": "t1", "prompts": ["x"], "mode": "gui_pc_web", "target_profile": "p_api"}],
    }
    r = await client.post("/api/v1/batches", json=body, headers=h)
    assert r.status_code == 422  # pydantic validator rejects


async def test_list_batches(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(url="https://api.example.com/v1/chat/completions", json={"choices": [{"message": {"content": "x"}}]})
    h = await _login(client)
    body = {
        "name": "b1", "mode": "api", "concurrency": 1,
        "samples": [{"id": "t1", "prompts": ["x"], "mode": "api", "target_profile": "p_api"}],
    }
    await client.post("/api/v1/batches", json=body, headers=h)
    r = await client.get("/api/v1/batches", headers=h)
    assert r.status_code == 200
    assert len(r.json()) >= 1
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/integration/test_batches_endpoints.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/autoagent/api/batches.py src/autoagent/main.py tests/integration/test_batches_endpoints.py
git commit -m "feat(api): batch CRUD, upload, results download, cancel"
```

---

## Task 21: Config + devices endpoints

**Files:**
- Create: `src/autoagent/api/config.py`
- Create: `src/autoagent/api/devices.py`
- Modify: `src/autoagent/main.py`
- Create: `tests/integration/test_config_endpoints.py`

- [ ] **Step 1: Write `src/autoagent/api/config.py`**

```python
from fastapi import APIRouter, Depends, HTTPException

from autoagent.auth.deps import require_user
from autoagent.models.api import DefaultsConfig, VLMConfig
from autoagent.storage.configs import get_config, put_config

router = APIRouter(prefix="/config", tags=["config"], dependencies=[Depends(require_user)])


@router.get("/vlm", response_model=VLMConfig | None)
async def get_vlm() -> VLMConfig | None:
    v = await get_config("vlm")
    if v is None:
        return None
    return VLMConfig.model_validate(v)


@router.put("/vlm", response_model=VLMConfig)
async def put_vlm(body: VLMConfig) -> VLMConfig:
    await put_config("vlm", body.model_dump())
    return body


@router.get("/defaults", response_model=DefaultsConfig)
async def get_defaults() -> DefaultsConfig:
    v = await get_config("defaults")
    return DefaultsConfig.model_validate(v) if v else DefaultsConfig()


@router.put("/defaults", response_model=DefaultsConfig)
async def put_defaults(body: DefaultsConfig) -> DefaultsConfig:
    await put_config("defaults", body.model_dump())
    return body
```

- [ ] **Step 2: Write `src/autoagent/api/devices.py` (stub for P0)**

```python
from fastapi import APIRouter, Depends, HTTPException

from autoagent.auth.deps import require_user

router = APIRouter(prefix="/devices", tags=["devices"], dependencies=[Depends(require_user)])


@router.get("")
async def list_devices() -> list:
    # Android devices — populated in Plan 4
    return []


@router.post("/{serial}/connect")
async def connect(serial: str) -> dict:
    raise HTTPException(status_code=501, detail="device support arrives in plan 4")


@router.post("/{serial}/disconnect")
async def disconnect(serial: str) -> dict:
    raise HTTPException(status_code=501, detail="device support arrives in plan 4")
```

- [ ] **Step 3: Update `src/autoagent/main.py`**

```python
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
```

- [ ] **Step 4: Write `tests/integration/test_config_endpoints.py`**

```python
import pytest
from httpx import ASGITransport, AsyncClient

from autoagent.auth.passwords import hash_password
from autoagent.storage.database import init_db
from autoagent.storage.users import upsert_user


@pytest.fixture
async def client():
    await init_db()
    await upsert_user("admin", hash_password("pw"))
    from autoagent.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _h(client):
    r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def test_defaults_roundtrip(client):
    h = await _h(client)
    r = await client.get("/api/v1/config/defaults", headers=h)
    assert r.status_code == 200
    assert r.json()["retry"] == 2

    new_vals = {"api_timeout_sec": 30, "gui_timeout_sec": 300, "retry": 5, "concurrency": 2, "verbose_logs": False}
    r = await client.put("/api/v1/config/defaults", json=new_vals, headers=h)
    assert r.status_code == 200

    r = await client.get("/api/v1/config/defaults", headers=h)
    assert r.json() == new_vals


async def test_vlm_config_roundtrip(client):
    h = await _h(client)
    r = await client.get("/api/v1/config/vlm", headers=h)
    assert r.status_code == 200
    assert r.json() is None

    body = {"base_url": "https://vlm.example.com/v1", "model": "v1", "api_key_env": "VLM_KEY"}
    r = await client.put("/api/v1/config/vlm", json=body, headers=h)
    assert r.status_code == 200

    r = await client.get("/api/v1/config/vlm", headers=h)
    assert r.json()["model"] == "v1"


async def test_devices_stub(client):
    h = await _h(client)
    r = await client.get("/api/v1/devices", headers=h)
    assert r.status_code == 200
    assert r.json() == []
```

- [ ] **Step 5: Run tests, verify pass**

Run: `pytest tests/integration/test_config_endpoints.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add src/autoagent/api/config.py src/autoagent/api/devices.py src/autoagent/main.py tests/integration/test_config_endpoints.py
git commit -m "feat(api): config (VLM, defaults) and devices stub endpoints"
```

---

## Task 22: App startup — bootstrap admin user + DB init

**Files:**
- Modify: `src/autoagent/main.py`
- Create: `src/autoagent/utils/__init__.py`
- Create: `src/autoagent/utils/logging.py`
- Create: `tests/integration/test_startup.py`

- [ ] **Step 1: Write `src/autoagent/utils/logging.py`**

```python
import logging
import sys


def configure_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s - %(message)s"
    ))
    root.setLevel(level)
    root.addHandler(handler)
```

- [ ] **Step 2: Replace `src/autoagent/main.py`**

```python
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
    allow_origins=["*"],  # Web UI (future plan) served from same host by default; tighten when deployed
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
```

- [ ] **Step 3: Write `tests/integration/test_startup.py`**

```python
from httpx import ASGITransport, AsyncClient


async def test_bootstrap_admin_and_health():
    from autoagent.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/health")
        assert r.status_code == 200
        # Admin user was bootstrapped by lifespan — can log in immediately
        r = await ac.post("/api/v1/auth/login", json={"username": "admin", "password": "admin_pw_1234"})
        assert r.status_code == 200
```

- [ ] **Step 4: Create `src/autoagent/utils/__init__.py` (empty)**

- [ ] **Step 5: Run tests, verify pass**

Run: `pytest tests/integration/test_startup.py -v`
Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
git add src/autoagent/main.py src/autoagent/utils tests/integration/test_startup.py
git commit -m "feat(main): FastAPI lifespan with admin bootstrap, CORS, health"
```

---

## Task 23: End-to-end integration test

**Files:**
- Create: `tests/integration/test_e2e_batch.py`

- [ ] **Step 1: Write `tests/integration/test_e2e_batch.py`**

```python
import asyncio
import json

import pytest
import yaml
from httpx import ASGITransport, AsyncClient
from pytest_httpx import HTTPXMock


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setenv("OPENAI_TEST_KEY", "sk-test")
    from autoagent.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def test_e2e_full_batch_via_http(client, httpx_mock: HTTPXMock):
    # Mock three upstream LLM replies
    for text in ("r1", "r2", "r3"):
        httpx_mock.add_response(
            url="https://api.example.com/v1/chat/completions",
            json={"choices": [{"message": {"content": text}}]},
        )

    # 1. Login
    r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin_pw_1234"})
    assert r.status_code == 200
    h = {"Authorization": f"Bearer {r.json()['token']}"}

    # 2. Create profile
    profile_yaml = yaml.safe_dump({
        "name": "openai_compat", "platform": "api",
        "api": {"base_url": "https://api.example.com/v1", "model": "m", "api_key_env": "OPENAI_TEST_KEY"},
    })
    r = await client.post("/api/v1/profiles/openai_compat", json={"yaml": profile_yaml}, headers=h)
    assert r.status_code == 201

    # 3. Upload batch
    jsonl = "\n".join(
        json.dumps({"id": f"t{i}", "prompts": [f"prompt{i}"], "mode": "api", "target_profile": "openai_compat"})
        for i in range(3)
    )
    files = {"file": ("b.jsonl", jsonl, "application/x-ndjson")}
    data = {"name": "e2e", "mode": "api", "concurrency": "2"}
    r = await client.post("/api/v1/batches/upload", files=files, data=data, headers=h)
    assert r.status_code == 201
    batch_id = r.json()["batch_id"]

    # 4. Poll until done
    for _ in range(40):
        await asyncio.sleep(0.1)
        r = await client.get(f"/api/v1/batches/{batch_id}", headers=h)
        if r.json()["status"] in ("done", "failed"):
            break
    detail = r.json()
    assert detail["status"] == "done"
    assert detail["total"] == 3
    assert detail["done"] == 3
    assert detail["failed"] == 0
    assert len(detail["samples"]) == 3

    # 5. Download results JSONL
    r = await client.get(f"/api/v1/batches/{batch_id}/results", headers=h)
    assert r.status_code == 200
    lines = r.text.strip().splitlines()
    assert len(lines) == 3
    for line in lines:
        d = json.loads(line)
        assert d["status"] == "done"
        assert len(d["responses"]) == 1
```

- [ ] **Step 2: Run the full suite**

Run: `pytest -v`
Expected: All tests (unit + integration + e2e) pass.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_e2e_batch.py
git commit -m "test: end-to-end batch flow via HTTP API"
```

---

## Task 24: README + operator docs

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace `README.md`**

````markdown
# AutoAgent Test — Backend MVP

Backend service for batch testing of conversational AI products via OpenAI-compatible APIs.

## Status

**Backend only (Plan 1/5).** Web UI (Plan 2), Web GUI executor (Plan 3), and Android executor (Plan 4) are separate plans. API mode is the only executor currently wired.

## Requirements

- Python 3.10+
- Optional: Docker (later plan)

## Setup

```bash
cp .env.example .env
# Edit .env: set ADMIN_PASSWORD and JWT_SECRET (at least 32 chars)

pip install -e ".[dev]"
```

## Run

```bash
uvicorn autoagent.main:app --host 0.0.0.0 --port 8000 --reload
```

The admin user is bootstrapped on first start from `ADMIN_USERNAME` / `ADMIN_PASSWORD`.

Health check: `curl http://localhost:8000/health`

## Quick start — run one prompt

```bash
# 1. Log in
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"your_password"}' | jq -r .token)

# 2. Create a profile (YAML string inside a JSON body)
curl -X POST http://localhost:8000/api/v1/profiles/openai_gpt4 \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"yaml": "name: openai_gpt4\nplatform: api\napi:\n  base_url: https://api.openai.com/v1\n  model: gpt-4o\n  api_key_env: OPENAI_KEY\n"}'

# 3. Set env var before running the service: export OPENAI_KEY=sk-...
# 4. Run a single-prompt sync test
curl -X POST http://localhost:8000/api/v1/tests/sync \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"id":"t1","prompts":["hello"],"mode":"api","target_profile":"openai_gpt4"}'
```

## Batch file formats

**JSONL** (recommended):

```jsonl
{"id": "t1", "prompts": ["hello"], "mode": "api", "target_profile": "openai_gpt4"}
{"id": "t2", "prompts": ["hi", "再说"], "mode": "api", "target_profile": "openai_gpt4", "new_session": false}
```

**JSON** — list of the same sample objects, or `{"samples": [...]}`

**CSV** — columns: `id,prompts,mode,target_profile,new_session,metadata`. Multi-turn prompts are joined by the Unicode Unit Separator `\u241f`.

## API reference

Auto-generated OpenAPI: `http://localhost:8000/docs`

Key endpoints:
- `POST /api/v1/auth/login` — get JWT
- `POST /api/v1/tests/sync` — single test, blocking
- `POST /api/v1/tests` — single test, async (returns `task_id`)
- `GET  /api/v1/tests/{task_id}` — poll async result
- `POST /api/v1/batches` — batch via JSON body
- `POST /api/v1/batches/upload` — batch via file upload (JSONL/JSON/CSV)
- `GET  /api/v1/batches/{id}` — batch detail + samples
- `GET  /api/v1/batches/{id}/results` — download JSONL
- `POST /api/v1/batches/{id}/cancel`
- `GET/POST/PUT/DELETE /api/v1/profiles/...`
- `POST /api/v1/profiles/validate`
- `GET/PUT /api/v1/config/vlm`, `/api/v1/config/defaults`

## Development

```bash
pytest              # run all tests
pytest -v           # verbose
pytest tests/unit   # unit only
ruff check .        # lint
ruff format .       # format
```

## Architecture

See:
- `docs/superpowers/specs/2026-04-21-agent-ai-testing-tool-design.md`
- `docs/superpowers/plans/2026-04-21-plan-1-backend-mvp.md`

## Next plans

- Plan 2: React Web UI
- Plan 3: Web GUI Executor (Playwright)
- Plan 4: Android Executor (uiautomator2 + OCR)
- Plan 5: Packaging, monthly backups, Docker
````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: operator README with quickstart and API reference"
```

---

## Task 25: Final verification

- [ ] **Step 1: Run full test suite**

Run: `pytest -v`
Expected: **All tests pass.** Count should be roughly:

- Unit: test_settings (2), test_database (1), test_auth (4), test_api_schemas (6), test_profiles (9), test_loaders (5), test_executor_base (4), test_api_executor (4), test_result_writer (2), test_batch_storage (4), test_configs_storage (2), test_webhooks (3), test_scheduler (2) = **48**
- Integration: test_auth_endpoints (3), test_profiles_endpoints (2), test_tests_endpoints (2), test_batches_endpoints (4), test_config_endpoints (3), test_startup (1), test_e2e_batch (1) = **16**
- **Total: ~64 tests passing.**

- [ ] **Step 2: Lint and format**

```bash
ruff check .
ruff format --check .
```

Fix any issues, commit with `chore: ruff lint/format`.

- [ ] **Step 3: Smoke-test the server manually**

```bash
export ADMIN_USERNAME=admin
export ADMIN_PASSWORD=admin_pw_1234
export JWT_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")
uvicorn autoagent.main:app &
sleep 2
curl -s http://localhost:8000/health
# Expected: {"status":"ok"}
```

- [ ] **Step 4: Tag MVP**

```bash
git tag -a backend-mvp-v0.1.0 -m "Plan 1 complete: backend MVP"
```

---

## Acceptance criteria (Plan 1 done when:)

1. ✅ `pytest` is green (64+ tests passing)
2. ✅ `ruff check` is clean
3. ✅ Manual smoke test: login → create profile → run sync test → returns response
4. ✅ Manual smoke test: upload 3-sample JSONL batch → batch shows `status=done`, `/results` downloads full JSONL
5. ✅ Missing `JWT_SECRET` or weak (<32 chars) causes startup failure (validated by Task 2 tests)
6. ✅ Missing `api_key_env` at execution time yields `failed` sample with clear error (validated by Task 13 tests)
7. ✅ Batch with mismatched sample mode rejected with 422 (validated by Task 20 tests)
8. ✅ Async test lifecycle (POST → poll GET) works end-to-end (validated by Task 19 tests)
9. ✅ Webhook callback delivered on sample completion (unit test validates sender; E2E with callback left to Plan 3 integration)
10. ✅ Profile validation endpoint correctly flags bad YAML

---

## Handoff to Plan 2 (Web UI)

After Plan 1 ships:

- **API is stable.** Plan 2 builds React frontend against the existing `/api/v1/*` endpoints.
- **WebSocket progress** stream is NOT in Plan 1 — Plan 2 will either add it or poll. Recommend adding it in Plan 2 since it's the primary consumer.
- **Static serving** — Plan 2 will either build the React app into `static/` and have FastAPI serve it, or run Vite dev server separately with CORS already allowed (Task 22).
