from __future__ import annotations

import asyncio
import json
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from autoagent.auth.deps import require_user
from autoagent.devices.adb import AdbCommandError, get_screen_resolution, run_input_command

log = logging.getLogger(__name__)

router = APIRouter(prefix="/devices", tags=["device_stream"])

_SERIAL_RE = re.compile(r"^[a-zA-Z0-9._:\-]+$")

# serial → active screenrecord asyncio subprocess
_active_streams: dict[str, asyncio.subprocess.Process] = {}


def _validate_serial(serial: str) -> None:
    if not _SERIAL_RE.fullmatch(serial):
        raise HTTPException(status_code=400, detail=f"Invalid device serial: {serial!r}")


class DeviceInputRequest(BaseModel):
    type: str
    x: int | None = None
    y: int | None = None
    x1: int | None = None
    y1: int | None = None
    x2: int | None = None
    y2: int | None = None
    duration_ms: int = 300
    value: str | None = None
    keycode: str | None = None

    def to_cmd(self) -> dict:
        if self.type == "tap":
            return {"type": "tap", "x": self.x, "y": self.y}
        if self.type == "swipe":
            return {
                "type": "swipe",
                "x1": self.x1,
                "y1": self.y1,
                "x2": self.x2,
                "y2": self.y2,
                "duration_ms": self.duration_ms,
            }
        if self.type == "text":
            return {"type": "text", "value": self.value or ""}
        if self.type == "key":
            return {"type": "key", "keycode": self.keycode or ""}
        raise HTTPException(status_code=422, detail=f"Unknown input type: {self.type!r}")


@router.post("/{serial}/input", status_code=204, dependencies=[Depends(require_user)])
async def device_input(serial: str, body: DeviceInputRequest) -> None:
    _validate_serial(serial)
    cmd = body.to_cmd()
    try:
        await asyncio.to_thread(run_input_command, serial, cmd)
    except AdbCommandError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


async def _kill_proc(proc: asyncio.subprocess.Process) -> None:
    try:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            proc.kill()
    except Exception:
        pass


async def _stream_h264(ws: WebSocket, serial: str) -> None:
    try:
        w, h = await asyncio.to_thread(get_screen_resolution, serial, 720)
    except AdbCommandError as exc:
        await ws.send_text(json.dumps({"error": "device_not_found", "detail": str(exc)}))
        await ws.close()
        return

    old = _active_streams.pop(serial, None)
    if old is not None:
        await _kill_proc(old)

    proc = await asyncio.create_subprocess_exec(
        "adb",
        "-s",
        serial,
        "exec-out",
        "sh",
        "-c",
        f"screenrecord --output-format=h264 --size={w}x{h} -"
        " 2>/tmp/sr_err.txt; cat /tmp/sr_err.txt >&2",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _active_streams[serial] = proc
    log.info("device_stream %s started pid=%s size=%sx%s", serial, proc.pid, w, h)
    first = True
    try:
        while True:
            try:
                chunk = await asyncio.wait_for(proc.stdout.read(65536), timeout=8.0)
            except asyncio.TimeoutError:
                try:
                    stderr_data = await asyncio.wait_for(proc.stderr.read(4096), timeout=1.0)
                except asyncio.TimeoutError:
                    stderr_data = b""
                log.warning(
                    "device_stream %s no data in 8s, stderr=%r",
                    serial,
                    stderr_data.decode(errors="replace"),
                )
                await ws.send_text(
                    json.dumps(
                        {
                            "error": "no_data",
                            "detail": "screenrecord produced no output",
                            "stderr": stderr_data.decode(errors="replace"),
                        }
                    )
                )
                await ws.close()
                return
            if not chunk:
                break
            if first:
                log.info(
                    "device_stream %s first chunk: %d bytes magic=%s",
                    serial,
                    len(chunk),
                    chunk[:8].hex(),
                )
                first = False
            await ws.send_bytes(chunk)
    except (WebSocketDisconnect, Exception):
        raise
    finally:
        _active_streams.pop(serial, None)
        await _kill_proc(proc)
        log.info("device_stream %s stopped", serial)

    await ws.send_text(json.dumps({"error": "screenrecord_exited", "returncode": proc.returncode}))
    await ws.close()


@router.websocket("/{serial}/stream")
async def device_stream(websocket: WebSocket, serial: str, token: str | None = None) -> None:
    from autoagent.auth.jwt import decode_token

    try:
        if token is None:
            await websocket.close(code=4401)
            return
        decode_token(token)
    except Exception:
        await websocket.close(code=4401)
        return

    _validate_serial(serial)
    await websocket.accept()
    try:
        await _stream_h264(websocket, serial)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.warning("device_stream %s unexpected error: %s", serial, exc)
        try:
            await websocket.send_text(json.dumps({"error": "internal", "detail": str(exc)}))
            await websocket.close()
        except Exception:
            pass
