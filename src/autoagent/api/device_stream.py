from __future__ import annotations

import asyncio
import json
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from autoagent.auth.bearer import BearerAuthError, resolve_bearer_subject
from autoagent.auth.deps import require_user
from autoagent.devices.adb import AdbCommandError, get_screen_resolution, run_input_command

log = logging.getLogger(__name__)

router = APIRouter(prefix="/devices", tags=["device_stream"])

_SERIAL_RE = re.compile(r"^[a-zA-Z0-9._:\-]+$")

# serial → active screenrecord asyncio subprocess
_active_streams: dict[str, asyncio.subprocess.Process] = {}

# Stream tuning bounds. Default width 720 / bitrate 6 Mbps is a balance: high
# enough to read text, low enough that a wifi-adb device (common here) doesn't
# choke on the ~20 Mbps screenrecord default, which inflates both latency and
# effective frame rate over the network.
_DEFAULT_WIDTH = 720
_MIN_WIDTH = 240
_MAX_WIDTH = 1080
_DEFAULT_BITRATE_MBPS = 6
_MIN_BITRATE_MBPS = 1
_MAX_BITRATE_MBPS = 20


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def _resolve_stream_params(width: int | None, bitrate: int | None) -> tuple[int, int]:
    """Clamp caller-supplied width (px) and bitrate (Mbps) to safe bounds.

    Falls back to the defaults when a param is omitted. Pure — unit-tested.
    """
    w = _DEFAULT_WIDTH if width is None else _clamp(width, _MIN_WIDTH, _MAX_WIDTH)
    if bitrate is None:
        b = _DEFAULT_BITRATE_MBPS
    else:
        b = _clamp(bitrate, _MIN_BITRATE_MBPS, _MAX_BITRATE_MBPS)
    return w, b


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


def _require_query_token(token: str | None) -> None:
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        resolve_bearer_subject(token)
    except BearerAuthError as e:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from e


@router.get("/{serial}/screenshot.png")
async def device_screenshot(serial: str, token: str | None = None) -> Response:
    """One-shot PNG via `adb exec-out screencap -p`.

    Auth is via `?token=` so the URL can be used directly as an <img src>,
    which can't carry an Authorization header.
    """
    _require_query_token(token)
    _validate_serial(serial)
    proc = await asyncio.create_subprocess_exec(
        "adb",
        "-s",
        serial,
        "exec-out",
        "screencap",
        "-p",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=8.0)
    except asyncio.TimeoutError as e:
        proc.kill()
        raise HTTPException(status_code=504, detail="screencap timeout") from e
    if proc.returncode != 0 or not stdout:
        raise HTTPException(
            status_code=502,
            detail=f"screencap failed rc={proc.returncode} err={stderr[:200]!r}",
        )
    # Strict no-store so the <img>?ts= polling actually re-fetches.
    return Response(
        content=stdout,
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


async def _spawn_screenrecord(
    serial: str,
    *,
    width: int = _DEFAULT_WIDTH,
    bitrate_mbps: int = _DEFAULT_BITRATE_MBPS,
) -> tuple[asyncio.subprocess.Process, int, int]:
    """Start `screenrecord` on the device and return (proc, width, height).

    Replaces any prior stream for the same serial to avoid two screenrecord
    processes fighting for the encoder.
    """
    w, h = await asyncio.to_thread(get_screen_resolution, serial, width)
    old = _active_streams.pop(serial, None)
    if old is not None:
        await _kill_proc(old)
    # Use exec-out directly; the prior shell wrapper that staged stderr through
    # /tmp/sr_err.txt failed on devices where /tmp is not writable (busybox
    # would emit "sh: can't create ..." to stdout and contaminate the H264
    # stream). adb's exec-out already keeps stdout/stderr cleanly separated.
    proc = await asyncio.create_subprocess_exec(
        "adb",
        "-s",
        serial,
        "exec-out",
        "screenrecord",
        "--output-format=h264",
        f"--size={w}x{h}",
        f"--bit-rate={bitrate_mbps * 1_000_000}",
        "-",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _active_streams[serial] = proc
    return proc, w, h


@router.get("/{serial}/stream.h264")
async def device_stream_http(
    serial: str,
    token: str | None = None,
    width: int | None = None,
    bitrate: int | None = None,
) -> StreamingResponse:
    """H.264 Annex-B byte stream over plain HTTP chunked transfer.

    Same capture pipeline as the WebSocket endpoint, but works through L7
    reverse proxies (e.g. openresty) that strip the WebSocket `Upgrade`
    header. The browser consumes this with `fetch().body.getReader()` and
    feeds chunks to WebCodecs `VideoDecoder`.

    `X-Accel-Buffering: no` asks nginx/openresty not to buffer the
    response, which is required for sub-second latency.
    """
    _require_query_token(token)
    _validate_serial(serial)
    req_w, req_b = _resolve_stream_params(width, bitrate)
    try:
        proc, w, h = await _spawn_screenrecord(serial, width=req_w, bitrate_mbps=req_b)
    except AdbCommandError as e:
        raise HTTPException(status_code=502, detail=f"device not reachable: {e}") from e
    log.info("device_stream_http %s started pid=%s size=%sx%s", serial, proc.pid, w, h)

    async def gen() -> asyncio.AsyncIterator[bytes]:
        first = True
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(proc.stdout.read(65536), timeout=8.0)
                except asyncio.TimeoutError:
                    try:
                        stderr_data = await asyncio.wait_for(
                            proc.stderr.read(4096), timeout=1.0
                        )
                    except asyncio.TimeoutError:
                        stderr_data = b""
                    log.warning(
                        "device_stream_http %s no data in 8s, stderr=%r",
                        serial,
                        stderr_data.decode(errors="replace"),
                    )
                    return
                if not chunk:
                    return
                if first:
                    log.info(
                        "device_stream_http %s first chunk: %d bytes magic=%s",
                        serial,
                        len(chunk),
                        chunk[:8].hex(),
                    )
                    # Valid H264 starts with an Annex-B NAL start code. Anything
                    # else (typically shell error text) means the device can't
                    # produce a stream — drain stderr and bail with the real
                    # message instead of letting the browser decoder choke.
                    if not chunk.startswith(b"\x00\x00\x00\x01") and not chunk.startswith(
                        b"\x00\x00\x01"
                    ):
                        try:
                            err_data = await asyncio.wait_for(
                                proc.stderr.read(4096), timeout=0.5
                            )
                        except asyncio.TimeoutError:
                            err_data = b""
                        log.warning(
                            "device_stream_http %s non-H264 first chunk, stdout=%r stderr=%r",
                            serial,
                            chunk[:200].decode(errors="replace"),
                            err_data.decode(errors="replace"),
                        )
                        return
                    first = False
                yield chunk
        finally:
            _active_streams.pop(serial, None)
            await _kill_proc(proc)
            log.info("device_stream_http %s stopped", serial)

    return StreamingResponse(
        gen(),
        media_type="video/h264",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",  # tell nginx/openresty not to buffer
        },
    )


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


async def _stream_h264(
    ws: WebSocket,
    serial: str,
    *,
    width: int = _DEFAULT_WIDTH,
    bitrate_mbps: int = _DEFAULT_BITRATE_MBPS,
) -> None:
    try:
        proc, w, h = await _spawn_screenrecord(serial, width=width, bitrate_mbps=bitrate_mbps)
    except AdbCommandError as exc:
        await ws.send_text(json.dumps({"error": "device_not_found", "detail": str(exc)}))
        await ws.close()
        return
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
async def device_stream(
    websocket: WebSocket,
    serial: str,
    token: str | None = None,
    width: int | None = None,
    bitrate: int | None = None,
) -> None:
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
    req_w, req_b = _resolve_stream_params(width, bitrate)
    await websocket.accept()
    try:
        await _stream_h264(websocket, serial, width=req_w, bitrate_mbps=req_b)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.warning("device_stream %s unexpected error: %s", serial, exc)
        try:
            await websocket.send_text(json.dumps({"error": "internal", "detail": str(exc)}))
            await websocket.close()
        except Exception:
            pass
