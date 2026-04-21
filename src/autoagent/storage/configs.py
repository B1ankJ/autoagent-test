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
