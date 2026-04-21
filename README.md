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
