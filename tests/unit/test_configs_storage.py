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
