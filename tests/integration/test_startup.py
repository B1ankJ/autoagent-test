import anyio
import pytest
from httpx import ASGITransport, AsyncClient


async def test_bootstrap_admin_and_health():
    from autoagent.main import app

    # Manually drive the ASGI lifespan so init_db + admin bootstrap run
    receive_queue: anyio.abc.ObjectReceiveStream
    send_queue: anyio.abc.ObjectSendStream
    send_queue, receive_queue = anyio.create_memory_object_stream(1)

    startup_complete = anyio.Event()
    shutdown_send, shutdown_receive = anyio.create_memory_object_stream(1)

    async def run_lifespan():
        scope = {"type": "lifespan", "asgi": {"version": "3.0"}}

        async def receive():
            return await receive_queue.receive()

        async def send(message):
            if message["type"] == "lifespan.startup.complete":
                startup_complete.set()
            elif message["type"] == "lifespan.shutdown.complete":
                await shutdown_send.send(message)

        await app(scope, receive, send)

    async with anyio.create_task_group() as tg:
        tg.start_soon(run_lifespan)
        await send_queue.send({"type": "lifespan.startup"})
        await startup_complete.wait()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/health")
            assert r.status_code == 200
            # Admin user was bootstrapped by lifespan — can log in immediately
            r = await ac.post("/api/v1/auth/login", json={"username": "admin", "password": "admin_pw_1234"})
            assert r.status_code == 200

        await send_queue.send({"type": "lifespan.shutdown"})
        await shutdown_receive.receive()
        tg.cancel_scope.cancel()
