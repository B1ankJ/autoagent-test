# Device Screen Streaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Devices 页面为每台 Android 设备新增模态弹窗，H264 via WebSocket 实时串流画面，支持 tap / swipe / text / system key 四种交互。

**Architecture:** 后端新增 `device_stream.py` 路由，WebSocket 端点启动 `adb exec-out screenrecord --output-format=h264` 子进程并推送裸流，REST 端点接收交互指令并执行对应 `adb input` 命令。前端 `useDeviceStream` hook 用 WebCodecs VideoDecoder 解码 H264，渲染到 `<canvas>`；`DeviceStreamModal` 组件捕获鼠标事件换算坐标并 POST 交互。

**Tech Stack:** Python asyncio subprocess, FastAPI WebSocket, adb input, React + TypeScript, WebCodecs API (Chrome 94+), AntD 5 Modal

---

## File Map

| 文件 | 操作 | 职责 |
|---|---|---|
| `src/autoagent/devices/adb.py` | 修改 | 新增 `get_screen_resolution()` 和 `run_input_command()` |
| `src/autoagent/api/device_stream.py` | 新建 | WebSocket 串流端点 + REST 输入端点 |
| `src/autoagent/main.py` | 修改 | 注册 device_stream router |
| `tests/unit/test_device_stream.py` | 新建 | 输入端点 + adb 命令生成单元测试 |
| `web/src/types/api.ts` | 修改 | 新增 `DeviceInputRequest` 类型 |
| `web/src/api/deviceStream.ts` | 新建 | `useDeviceStream` hook + `postDeviceInput` |
| `web/src/components/DeviceStreamModal.tsx` | 新建 | 弹窗组件（canvas + 交互 + 侧边栏） |
| `web/src/pages/Devices/Index.tsx` | 修改 | 每行加"查看画面"按钮 |
| `web/src/pages/Devices/Index.test.tsx` | 修改 | mock `useDeviceStream` + 新增按钮渲染测试 |

---

## Task 1: adb 工具函数（分辨率 + 输入命令）

**Files:**
- Modify: `src/autoagent/devices/adb.py`
- Test: `tests/unit/test_device_stream.py`（本 task 仅写此文件中的 adb 相关测试）

- [ ] **Step 1: 新建测试文件，写 `get_screen_resolution` 的失败测试**

```python
# tests/unit/test_device_stream.py
from unittest.mock import MagicMock, patch

import pytest

from autoagent.devices.adb import get_screen_resolution, run_input_command, AdbCommandError


def test_get_screen_resolution_parses_portrait():
    with patch("autoagent.devices.adb._run_adb") as mock:
        mock.return_value = MagicMock(stdout="Physical size: 1080x2400\n")
        w, h = get_screen_resolution("emulator-5554")
    assert w == 1080
    assert h == 2400


def test_get_screen_resolution_scales_to_720_width():
    with patch("autoagent.devices.adb._run_adb") as mock:
        mock.return_value = MagicMock(stdout="Physical size: 1080x2400\n")
        w, h = get_screen_resolution("emulator-5554", target_width=720)
    assert w == 720
    assert h == 1600  # 2400 * 720 / 1080 = 1600


def test_get_screen_resolution_raises_on_bad_output():
    with patch("autoagent.devices.adb._run_adb") as mock:
        mock.return_value = MagicMock(stdout="unexpected output\n")
        with pytest.raises(AdbCommandError):
            get_screen_resolution("emulator-5554")
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
python3.11 -m pytest tests/unit/test_device_stream.py::test_get_screen_resolution_parses_portrait -v
```

预期：`ImportError: cannot import name 'get_screen_resolution'`

- [ ] **Step 3: 在 `adb.py` 末尾添加 `get_screen_resolution` 实现**

```python
import re as _re

def get_screen_resolution(serial: str, target_width: int = 720) -> tuple[int, int]:
    """Return (width, height) scaled so width == target_width, preserving aspect ratio."""
    proc = _run_adb("-s", serial, "shell", "wm", "size")
    match = _re.search(r"Physical size:\s*(\d+)x(\d+)", proc.stdout)
    if not match:
        raise AdbCommandError(f"Cannot parse screen resolution from: {proc.stdout!r}")
    native_w, native_h = int(match.group(1)), int(match.group(2))
    scaled_h = round(native_h * target_width / native_w)
    # Ensure both dimensions are even (H264 requirement)
    return target_width - target_width % 2, scaled_h - scaled_h % 2
```

注意：`import re as _re` 加在文件顶部现有 import 区域（与其他 stdlib import 合并）。

- [ ] **Step 4: 运行分辨率测试，确认通过**

```bash
python3.11 -m pytest tests/unit/test_device_stream.py -k "resolution" -v
```

预期：3 passed

- [ ] **Step 5: 写 `run_input_command` 测试**

追加到 `tests/unit/test_device_stream.py`：

```python
def test_run_input_tap():
    with patch("autoagent.devices.adb._run_adb") as mock:
        mock.return_value = MagicMock(stdout="")
        run_input_command("emulator-5554", {"type": "tap", "x": 360, "y": 640})
    mock.assert_called_once_with("-s", "emulator-5554", "shell", "input", "tap", "360", "640")


def test_run_input_swipe():
    with patch("autoagent.devices.adb._run_adb") as mock:
        mock.return_value = MagicMock(stdout="")
        run_input_command("emulator-5554", {"type": "swipe", "x1": 100, "y1": 500, "x2": 100, "y2": 200, "duration_ms": 300})
    mock.assert_called_once_with("-s", "emulator-5554", "shell", "input", "swipe", "100", "500", "100", "200", "300")


def test_run_input_key():
    with patch("autoagent.devices.adb._run_adb") as mock:
        mock.return_value = MagicMock(stdout="")
        run_input_command("emulator-5554", {"type": "key", "keycode": "KEYCODE_BACK"})
    mock.assert_called_once_with("-s", "emulator-5554", "shell", "input", "keyevent", "KEYCODE_BACK")


def test_run_input_text_escapes_spaces():
    with patch("autoagent.devices.adb._run_adb") as mock:
        mock.return_value = MagicMock(stdout="")
        run_input_command("emulator-5554", {"type": "text", "value": "hello world"})
    mock.assert_called_once_with("-s", "emulator-5554", "shell", "input", "text", "hello%sworld")


def test_run_input_text_escapes_special_chars():
    with patch("autoagent.devices.adb._run_adb") as mock:
        mock.return_value = MagicMock(stdout="")
        run_input_command("emulator-5554", {"type": "text", "value": "a&b|c"})
    # & and | must be backslash-escaped for the device shell
    args = mock.call_args[0]
    escaped = args[-1]
    assert "\\&" in escaped
    assert "\\|" in escaped


def test_run_input_rejects_invalid_type():
    with pytest.raises(AdbCommandError):
        run_input_command("emulator-5554", {"type": "unknown"})
```

- [ ] **Step 6: 运行测试，确认失败**

```bash
python3.11 -m pytest tests/unit/test_device_stream.py -k "input" -v
```

预期：`ImportError: cannot import name 'run_input_command'`

- [ ] **Step 7: 在 `adb.py` 末尾添加 `run_input_command` 实现**

```python
_SHELL_SPECIAL = set('&|;<>()$`\\"\'')


def _escape_text_for_adb(text: str) -> str:
    """Encode text for `adb shell input text`.

    Spaces become %s (adb input text convention).
    Shell special characters get backslash-escaped.
    """
    result = []
    for ch in text:
        if ch == " ":
            result.append("%s")
        elif ch in _SHELL_SPECIAL:
            result.append(f"\\{ch}")
        else:
            result.append(ch)
    return "".join(result)


def run_input_command(serial: str, cmd: dict) -> None:
    """Execute an adb input command on the device."""
    t = cmd.get("type")
    if t == "tap":
        _run_adb("-s", serial, "shell", "input", "tap", str(cmd["x"]), str(cmd["y"]))
    elif t == "swipe":
        _run_adb(
            "-s", serial, "shell", "input", "swipe",
            str(cmd["x1"]), str(cmd["y1"]), str(cmd["x2"]), str(cmd["y2"]),
            str(cmd.get("duration_ms", 300)),
        )
    elif t == "text":
        _run_adb("-s", serial, "shell", "input", "text", _escape_text_for_adb(cmd["value"]))
    elif t == "key":
        _run_adb("-s", serial, "shell", "input", "keyevent", cmd["keycode"])
    else:
        raise AdbCommandError(f"Unknown input type: {t!r}")
```

- [ ] **Step 8: 运行所有 adb 测试，确认通过**

```bash
python3.11 -m pytest tests/unit/test_device_stream.py -v
```

预期：全部 passed

- [ ] **Step 9: Commit**

```bash
git add src/autoagent/devices/adb.py tests/unit/test_device_stream.py
git commit -m "feat: add get_screen_resolution and run_input_command to adb utils"
```

---

## Task 2: 后端 device_stream.py — 输入端点

**Files:**
- Create: `src/autoagent/api/device_stream.py`
- Test: `tests/unit/test_device_stream.py`

- [ ] **Step 1: 追加输入端点的集成测试**

追加到 `tests/unit/test_device_stream.py`：

```python
import pytest
from httpx import AsyncClient, ASGITransport
from autoagent.main import app


@pytest.fixture
def auth_headers(monkeypatch):
    # bypass auth
    monkeypatch.setattr("autoagent.api.device_stream.require_user", lambda: None)
    monkeypatch.setattr("autoagent.auth.deps.require_user", lambda: "admin")
    return {"Authorization": "Bearer test-token"}


@pytest.mark.asyncio
async def test_input_tap_calls_adb(monkeypatch, auth_headers):
    calls = []

    def fake_run_input(serial, cmd):
        calls.append((serial, cmd))

    monkeypatch.setattr("autoagent.api.device_stream.run_input_command", fake_run_input)
    monkeypatch.setattr("autoagent.api.device_stream._validate_serial", lambda s: None)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/devices/emulator-5554/input",
            json={"type": "tap", "x": 100, "y": 200},
            headers=auth_headers,
        )
    assert resp.status_code == 204
    assert calls == [("emulator-5554", {"type": "tap", "x": 100, "y": 200})]


@pytest.mark.asyncio
async def test_input_rejects_bad_serial(monkeypatch, auth_headers):
    monkeypatch.setattr("autoagent.auth.deps.require_user", lambda: "admin")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/devices/../../etc/passwd/input",
            json={"type": "tap", "x": 0, "y": 0},
            headers=auth_headers,
        )
    assert resp.status_code in (400, 404, 422)
```

- [ ] **Step 2: 运行，确认失败**

```bash
python3.11 -m pytest tests/unit/test_device_stream.py -k "input_tap or bad_serial" -v
```

预期：`ImportError` 或 `404`（router 未注册）

- [ ] **Step 3: 新建 `src/autoagent/api/device_stream.py`**

```python
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

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

    def to_cmd(self) -> dict[str, Any]:
        if self.type == "tap":
            return {"type": "tap", "x": self.x, "y": self.y}
        if self.type == "swipe":
            return {"type": "swipe", "x1": self.x1, "y1": self.y1,
                    "x2": self.x2, "y2": self.y2, "duration_ms": self.duration_ms}
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
```

- [ ] **Step 4: 在 `main.py` 注册 router**

在 `main.py` 的 import 区追加：
```python
from autoagent.api.device_stream import router as device_stream_router
```

在 `app.include_router(devices_router, ...)` 之后追加：
```python
app.include_router(device_stream_router, prefix="/api/v1")
```

- [ ] **Step 5: 运行输入端点测试**

```bash
python3.11 -m pytest tests/unit/test_device_stream.py -k "input" -v
```

预期：passed（需根据实际 auth 依赖调整 fixture，见下方说明）

> **Auth 说明**：项目的 `require_user` 依赖从 JWT token 解析用户，测试中需 mock。参考 `tests/integration/` 下 `test_auth.py` 的 override 模式，在 conftest 里用 `app.dependency_overrides[require_user] = lambda: "admin"` 替代 monkeypatch。

- [ ] **Step 6: 运行快速套件确认无回归**

```bash
python3.11 -m pytest -q -m "not playwright and not android and not slow"
```

预期：全部 passed

- [ ] **Step 7: Commit**

```bash
git add src/autoagent/api/device_stream.py src/autoagent/main.py tests/unit/test_device_stream.py
git commit -m "feat: add device input REST endpoint with adb command dispatch"
```

---

## Task 3: 后端 WebSocket 串流端点

**Files:**
- Modify: `src/autoagent/api/device_stream.py`
- Test: `tests/unit/test_device_stream.py`

- [ ] **Step 1: 追加 WebSocket 串流测试**

追加到 `tests/unit/test_device_stream.py`：

```python
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_stream_kills_process_on_disconnect(monkeypatch):
    """WebSocket 断开时，screenrecord 子进程必须被终止。"""
    fake_proc = MagicMock()
    fake_proc.stdout = AsyncMock()
    # 第一次读返回数据，第二次返回空（模拟进程结束）
    fake_proc.stdout.read = AsyncMock(side_effect=[b"\x00\x00\x00\x01abc", b""])
    fake_proc.terminate = MagicMock()
    fake_proc.wait = AsyncMock(return_value=0)
    fake_proc.returncode = None

    async def fake_create_subprocess(*args, **kwargs):
        return fake_proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess)

    from autoagent.api.device_stream import _stream_h264

    frames_sent = []

    class FakeWS:
        async def send_bytes(self, data):
            frames_sent.append(data)
            raise WebSocketDisconnect()  # 断开

    with patch("autoagent.api.device_stream.get_screen_resolution", return_value=(720, 1600)):
        try:
            await _stream_h264(FakeWS(), "emulator-5554")
        except WebSocketDisconnect:
            pass

    fake_proc.terminate.assert_called_once()
    assert frames_sent  # 至少发送了一帧


@pytest.mark.asyncio
async def test_stream_sends_error_frame_on_immediate_exit(monkeypatch):
    """screenrecord 立即退出时，发送 JSON 错误帧后关闭连接。"""
    fake_proc = MagicMock()
    fake_proc.stdout = AsyncMock()
    fake_proc.stdout.read = AsyncMock(return_value=b"")  # 立即 EOF
    fake_proc.terminate = MagicMock()
    fake_proc.wait = AsyncMock(return_value=1)
    fake_proc.returncode = 1

    async def fake_create_subprocess(*args, **kwargs):
        return fake_proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess)

    from autoagent.api.device_stream import _stream_h264

    messages_sent = []

    class FakeWS:
        async def send_bytes(self, data):
            messages_sent.append(("bytes", data))

        async def send_text(self, data):
            messages_sent.append(("text", data))

        async def close(self):
            pass

    with patch("autoagent.api.device_stream.get_screen_resolution", return_value=(720, 1600)):
        await _stream_h264(FakeWS(), "emulator-5554")

    text_frames = [m for m in messages_sent if m[0] == "text"]
    assert any("error" in m[1] for m in text_frames)
```

- [ ] **Step 2: 运行，确认失败**

```bash
python3.11 -m pytest tests/unit/test_device_stream.py -k "stream" -v
```

预期：`ImportError: cannot import name '_stream_h264'`

- [ ] **Step 3: 在 `device_stream.py` 末尾添加串流逻辑**

```python
import json


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
    w, h = get_screen_resolution(serial, target_width=720)
    # 终止该 serial 上可能残留的旧进程
    old = _active_streams.pop(serial, None)
    if old is not None:
        await _kill_proc(old)

    proc = await asyncio.create_subprocess_exec(
        "adb", "-s", serial, "exec-out",
        "screenrecord", "--output-format=h264", f"--size={w}x{h}", "-",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _active_streams[serial] = proc
    log.info("device_stream %s started pid=%s size=%sx%s", serial, proc.pid, w, h)
    try:
        while True:
            chunk = await proc.stdout.read(65536)
            if not chunk:
                # 进程退出
                break
            await ws.send_bytes(chunk)
    except (WebSocketDisconnect, Exception):
        raise
    finally:
        _active_streams.pop(serial, None)
        await _kill_proc(proc)
        log.info("device_stream %s stopped", serial)

    # 进程异常退出 → 发送错误帧
    await ws.send_text(json.dumps({"error": "screenrecord_exited", "returncode": proc.returncode}))
    await ws.close()


@router.websocket("/{serial}/stream")
async def device_stream(websocket: WebSocket, serial: str, token: str | None = None) -> None:
    # WebSocket 无法携带自定义 header，token 通过 query param 传入
    from autoagent.auth.jwt import decode_token
    from autoagent.auth.bearer import BearerAuthError
    try:
        if token is None:
            await websocket.close(code=4401)
            return
        decode_token(token)  # 验证有效性，无效则抛异常
    except Exception:
        await websocket.close(code=4401)
        return

    _validate_serial(serial)
    await websocket.accept()
    try:
        await _stream_h264(websocket, serial)
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("device_stream %s error", serial)
```

> **Auth 说明**：`decode_token` 需要能从 JWT 中解出用户信息即可，无需查数据库。先看 `src/autoagent/auth/jwt.py` 确认函数签名，若函数名不同则对应调整。

- [ ] **Step 4: 运行串流测试**

```bash
python3.11 -m pytest tests/unit/test_device_stream.py -k "stream" -v
```

预期：passed

- [ ] **Step 5: 运行完整快速套件**

```bash
python3.11 -m pytest -q -m "not playwright and not android and not slow"
```

预期：全部 passed

- [ ] **Step 6: Commit**

```bash
git add src/autoagent/api/device_stream.py tests/unit/test_device_stream.py
git commit -m "feat: add H264 WebSocket stream endpoint for device screen"
```

---

## Task 4: 前端类型和 API 函数

**Files:**
- Modify: `web/src/types/api.ts`
- Create: `web/src/api/deviceStream.ts`

- [ ] **Step 1: 在 `web/src/types/api.ts` 末尾追加类型**

```typescript
export type DeviceInputType = 'tap' | 'swipe' | 'text' | 'key'

export interface DeviceInputTap {
  type: 'tap'
  x: number
  y: number
}

export interface DeviceInputSwipe {
  type: 'swipe'
  x1: number
  y1: number
  x2: number
  y2: number
  duration_ms?: number
}

export interface DeviceInputText {
  type: 'text'
  value: string
}

export interface DeviceInputKey {
  type: 'key'
  keycode: string
}

export type DeviceInputRequest =
  | DeviceInputTap
  | DeviceInputSwipe
  | DeviceInputText
  | DeviceInputKey
```

- [ ] **Step 2: 新建 `web/src/api/deviceStream.ts`**

```typescript
import { useCallback, useEffect, useRef, useState } from 'react'

import { getToken } from './client'
import { DeviceInputRequest } from '../types/api'
import { client } from './client'

export type StreamState = 'connecting' | 'live' | 'error' | 'unsupported' | 'closed'

export interface DeviceStreamHandle {
  canvasRef: React.RefObject<HTMLCanvasElement>
  state: StreamState
  latencyMs: number | null
  reconnect: () => void
}

const MAX_RETRIES = 3
const RETRY_DELAY_MS = 2000

export function useDeviceStream(serial: string | null): DeviceStreamHandle {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [state, setState] = useState<StreamState>('closed')
  const [latencyMs, setLatencyMs] = useState<number | null>(null)
  const retryCount = useRef(0)
  const wsRef = useRef<WebSocket | null>(null)
  const decoderRef = useRef<VideoDecoder | null>(null)
  const bufferRef = useRef<Uint8Array>(new Uint8Array(0))
  // SPS and PPS NALUs needed for decoder configuration
  const spsRef = useRef<Uint8Array | null>(null)
  const ppsRef = useRef<Uint8Array | null>(null)
  const frameCountRef = useRef(0)
  const frameTimestampRef = useRef(0)

  const connect = useCallback(() => {
    if (!serial) return
    if (typeof VideoDecoder === 'undefined') {
      setState('unsupported')
      return
    }

    setState('connecting')
    const token = getToken()
    const wsUrl = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/api/v1/devices/${encodeURIComponent(serial)}/stream?token=${token}`
    const ws = new WebSocket(wsUrl)
    wsRef.current = ws
    ws.binaryType = 'arraybuffer'

    // Reset state for new connection
    bufferRef.current = new Uint8Array(0)
    spsRef.current = null
    ppsRef.current = null
    frameCountRef.current = 0
    frameTimestampRef.current = 0

    // Initialize VideoDecoder
    const decoder = new VideoDecoder({
      output: (frame) => {
        const canvas = canvasRef.current
        if (canvas) {
          canvas.width = frame.displayWidth
          canvas.height = frame.displayHeight
          const ctx = canvas.getContext('2d')
          ctx?.drawImage(frame, 0, 0)
        }
        frame.close()
      },
      error: (e) => {
        console.error('VideoDecoder error', e)
      },
    })
    decoderRef.current = decoder

    ws.onopen = () => {
      retryCount.current = 0
      setState('live')
    }

    ws.onmessage = (event) => {
      if (typeof event.data === 'string') {
        // JSON control frame (e.g. error)
        try {
          const msg = JSON.parse(event.data)
          if (msg.error) setState('error')
        } catch {}
        return
      }

      const incoming = new Uint8Array(event.data as ArrayBuffer)
      // Append to buffer
      const combined = new Uint8Array(bufferRef.current.length + incoming.length)
      combined.set(bufferRef.current)
      combined.set(incoming, bufferRef.current.length)
      bufferRef.current = combined

      // Parse NAL units and feed to decoder
      parseAndDecodeNALUs(combined, decoder, spsRef, ppsRef, frameCountRef, frameTimestampRef, setLatencyMs)
    }

    ws.onclose = () => {
      decoder.close()
      if (retryCount.current < MAX_RETRIES) {
        retryCount.current++
        setTimeout(connect, RETRY_DELAY_MS)
      } else {
        setState('error')
      }
    }

    ws.onerror = () => {
      ws.close()
    }
  }, [serial])

  const reconnect = useCallback(() => {
    retryCount.current = 0
    wsRef.current?.close()
    connect()
  }, [connect])

  useEffect(() => {
    if (!serial) return
    connect()
    return () => {
      retryCount.current = MAX_RETRIES // prevent auto-retry on unmount
      wsRef.current?.close()
      decoderRef.current?.close()
    }
  }, [serial, connect])

  return { canvasRef, state, latencyMs, reconnect }
}

// Find all start code positions (00 00 00 01 or 00 00 01)
function findStartCodes(data: Uint8Array): number[] {
  const positions: number[] = []
  for (let i = 0; i < data.length - 3; i++) {
    if (data[i] === 0 && data[i + 1] === 0) {
      if (data[i + 2] === 0 && data[i + 3] === 1) {
        positions.push(i)
        i += 3
      } else if (data[i + 2] === 1) {
        positions.push(i)
        i += 2
      }
    }
  }
  return positions
}

function parseAndDecodeNALUs(
  buffer: Uint8Array,
  decoder: VideoDecoder,
  spsRef: React.MutableRefObject<Uint8Array | null>,
  ppsRef: React.MutableRefObject<Uint8Array | null>,
  frameCountRef: React.MutableRefObject<number>,
  frameTimestampRef: React.MutableRefObject<number>,
  setLatencyMs: (ms: number) => void,
) {
  const starts = findStartCodes(buffer)
  if (starts.length < 2) return // need at least 2 start codes to slice a complete NAL

  for (let i = 0; i < starts.length - 1; i++) {
    const scStart = starts[i]
    const scLen = buffer[scStart + 2] === 1 ? 3 : 4
    const nalStart = scStart + scLen
    const nalEnd = starts[i + 1]
    if (nalEnd <= nalStart) continue

    const nalu = buffer.slice(nalStart, nalEnd)
    if (nalu.length === 0) continue
    const nalType = nalu[0] & 0x1f

    if (nalType === 7) {
      spsRef.current = nalu
    } else if (nalType === 8) {
      ppsRef.current = nalu
      // Try to configure decoder once we have both SPS and PPS
      if (spsRef.current && decoder.state === 'unconfigured') {
        try {
          decoder.configure({ codec: 'avc1.42E01E', optimizeForLatency: true })
        } catch (e) {
          console.error('VideoDecoder configure failed', e)
        }
      }
    } else if ((nalType === 5 || nalType === 1) && decoder.state === 'configured') {
      // IDR (5) = keyframe, non-IDR (1) = delta
      const isKey = nalType === 5
      // Build Annex B chunk: prepend start code
      const chunkData = new Uint8Array(4 + nalu.length)
      chunkData.set([0, 0, 0, 1])
      chunkData.set(nalu, 4)

      const ts = frameTimestampRef.current
      frameTimestampRef.current += 33333 // ~30fps in microseconds
      frameCountRef.current++

      const wallStart = performance.now()
      decoder.decode(
        new EncodedVideoChunk({
          type: isKey ? 'key' : 'delta',
          timestamp: ts,
          data: chunkData,
        }),
      )
      // Rough latency: time from decode call to next frame output approximated here
      if (frameCountRef.current % 30 === 0) {
        setLatencyMs(Math.round(performance.now() - wallStart + 33))
      }
    }
  }
}

export async function postDeviceInput(serial: string, cmd: DeviceInputRequest): Promise<void> {
  await client.post(`/devices/${serial}/input`, cmd)
}
```

- [ ] **Step 3: 类型检查**

```bash
cd web && npx tsc --noEmit 2>&1 | head -20
```

预期：无错误

- [ ] **Step 4: Commit**

```bash
cd ..
git add web/src/types/api.ts web/src/api/deviceStream.ts
git commit -m "feat: add DeviceInputRequest types and useDeviceStream hook"
```

---

## Task 5: DeviceStreamModal 组件

**Files:**
- Create: `web/src/components/DeviceStreamModal.tsx`

- [ ] **Step 1: 新建 `web/src/components/DeviceStreamModal.tsx`**

```typescript
import { useCallback, useRef } from 'react'
import { Alert, Button, Modal, Space, Tag, Tooltip } from 'antd'

import { postDeviceInput, useDeviceStream } from '../api/deviceStream'
import { DeviceInputKey } from '../types/api'

interface Props {
  serial: string | null
  onClose: () => void
}

const KEY_BUTTONS: Array<{ label: string; keycode: DeviceInputKey['keycode'] }> = [
  { label: '◁ 返回', keycode: 'KEYCODE_BACK' },
  { label: '○ 主页', keycode: 'KEYCODE_HOME' },
  { label: '□ 任务', keycode: 'KEYCODE_APP_SWITCH' },
  { label: 'Enter', keycode: 'KEYCODE_ENTER' },
  { label: 'Del', keycode: 'KEYCODE_DEL' },
]

export function DeviceStreamModal({ serial, onClose }: Props) {
  const { canvasRef, state, latencyMs, reconnect } = useDeviceStream(serial)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const dragRef = useRef<{ x: number; y: number; t: number } | null>(null)

  const toDeviceCoords = useCallback(
    (canvas: HTMLCanvasElement, clientX: number, clientY: number) => {
      const rect = canvas.getBoundingClientRect()
      const scaleX = canvas.width / rect.width
      const scaleY = canvas.height / rect.height
      return {
        x: Math.round((clientX - rect.left) * scaleX),
        y: Math.round((clientY - rect.top) * scaleY),
      }
    },
    [],
  )

  const handleCanvasMouseDown = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      e.preventDefault()
      dragRef.current = { x: e.clientX, y: e.clientY, t: Date.now() }
    },
    [],
  )

  const handleCanvasMouseUp = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      e.preventDefault()
      if (!serial || !canvasRef.current || !dragRef.current) return
      const canvas = canvasRef.current
      const start = dragRef.current
      dragRef.current = null

      const dx = e.clientX - start.x
      const dy = e.clientY - start.y
      const dist = Math.sqrt(dx * dx + dy * dy)
      const durationMs = Math.max(100, Math.min(1000, Date.now() - start.t))

      if (dist > 8) {
        const p1 = toDeviceCoords(canvas, start.x, start.y)
        const p2 = toDeviceCoords(canvas, e.clientX, e.clientY)
        postDeviceInput(serial, { type: 'swipe', ...p1, x2: p2.x, y2: p2.y, duration_ms: durationMs }).catch(console.error)
      } else {
        const p = toDeviceCoords(canvas, e.clientX, e.clientY)
        postDeviceInput(serial, { type: 'tap', ...p }).catch(console.error)
      }
    },
    [serial, canvasRef, toDeviceCoords],
  )

  const handleKeyButton = useCallback(
    (keycode: string) => {
      if (!serial) return
      postDeviceInput(serial, { type: 'key', keycode }).catch(console.error)
    },
    [serial],
  )

  const handleTextKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        if (!serial || !textareaRef.current) return
        const value = textareaRef.current.value
        if (value) {
          postDeviceInput(serial, { type: 'text', value }).catch(console.error)
          textareaRef.current.value = ''
        }
      }
    },
    [serial],
  )

  return (
    <Modal
      open={!!serial}
      onCancel={onClose}
      footer={null}
      width={680}
      title={
        <Space>
          <span>{serial}</span>
          {state === 'live' && <Tag color="green">直播中{latencyMs != null ? ` ~${latencyMs}ms` : ''}</Tag>}
          {state === 'connecting' && <Tag color="blue">连接中</Tag>}
          {state === 'error' && <Tag color="red">连接失败</Tag>}
        </Space>
      }
      destroyOnClose
    >
      {state === 'unsupported' && (
        <Alert
          type="error"
          message="浏览器不支持 WebCodecs，请使用 Chrome 94+ 或 Firefox 130+"
        />
      )}

      <div style={{ display: 'flex', gap: 12 }}>
        {/* Canvas area */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
          <canvas
            ref={canvasRef}
            style={{
              width: '100%',
              background: '#000',
              borderRadius: 6,
              cursor: 'crosshair',
              userSelect: 'none',
              minHeight: 300,
            }}
            onMouseDown={handleCanvasMouseDown}
            onMouseUp={handleCanvasMouseUp}
            onDragStart={(e) => e.preventDefault()}
          />
          <Space>
            {KEY_BUTTONS.map((btn) => (
              <Button key={btn.keycode} size="small" onClick={() => handleKeyButton(btn.keycode)}>
                {btn.label}
              </Button>
            ))}
          </Space>
          {state === 'error' && (
            <Button onClick={reconnect}>重新连接</Button>
          )}
        </div>

        {/* Right sidebar */}
        <div style={{ width: 140, display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div>
            <div style={{ fontSize: 11, color: '#888', marginBottom: 4 }}>文字输入</div>
            <textarea
              ref={textareaRef}
              rows={3}
              placeholder="输入后按 Enter 发送…"
              style={{ width: '100%', resize: 'none', boxSizing: 'border-box', padding: '4px 6px', borderRadius: 4, border: '1px solid #d9d9d9', fontSize: 12 }}
              onKeyDown={handleTextKeyDown}
            />
            <div style={{ fontSize: 10, color: '#bbb' }}>Enter 发送 · Shift+Enter 换行</div>
          </div>

          {canvasRef.current && (
            <div style={{ fontSize: 11, color: '#888' }}>
              <div>分辨率</div>
              <div style={{ color: '#ccc' }}>{canvasRef.current.width} × {canvasRef.current.height}</div>
              {latencyMs != null && (
                <>
                  <div style={{ marginTop: 6 }}>延迟</div>
                  <div style={{ color: latencyMs < 200 ? '#4caf50' : '#ff9800' }}>{latencyMs}ms</div>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </Modal>
  )
}
```

- [ ] **Step 2: 类型检查**

```bash
cd web && npx tsc --noEmit 2>&1 | head -20
```

预期：无错误

- [ ] **Step 3: Commit**

```bash
cd ..
git add web/src/components/DeviceStreamModal.tsx
git commit -m "feat: add DeviceStreamModal with H264 canvas and interaction controls"
```

---

## Task 6: 接入 Devices 页面 + 前端测试

**Files:**
- Modify: `web/src/pages/Devices/Index.tsx`
- Modify: `web/src/pages/Devices/Index.test.tsx`

- [ ] **Step 1: 修改 `web/src/pages/Devices/Index.tsx`**

在文件顶部 import 区追加：
```typescript
import { useState } from 'react'
import { DeviceStreamModal } from '../../components/DeviceStreamModal'
```

在 `export function DevicesPage()` 函数体内，`useDevices()` 等 hook 调用之后追加：
```typescript
const [streamSerial, setStreamSerial] = useState<string | null>(null)
```

在 `return` 中的 `<Card ...>` 前追加：
```typescript
<DeviceStreamModal serial={streamSerial} onClose={() => setStreamSerial(null)} />
```

在 Actions 列的 `<Space wrap>` 内，其他 Button 之前追加：
```typescript
<Button
  size="small"
  disabled={!row.online}
  onClick={() => setStreamSerial(row.serial)}
>
  查看画面
</Button>
```

- [ ] **Step 2: 更新 `web/src/pages/Devices/Index.test.tsx`**

在 `vi.mock('../../api/devices', ...)` 之后追加：
```typescript
vi.mock('../../api/deviceStream', () => ({
  useDeviceStream: () => ({
    canvasRef: { current: null },
    state: 'closed',
    latencyMs: null,
    reconnect: vi.fn(),
  }),
  postDeviceInput: vi.fn(),
}))
```

追加测试：
```typescript
it('renders 查看画面 button for online device', () => {
  render(
    <MemoryRouter>
      <QueryClientProvider client={new QueryClient()}>
        <DevicesPage />
      </QueryClientProvider>
    </MemoryRouter>,
  )
  expect(screen.getByText('查看画面')).toBeInTheDocument()
})
```

- [ ] **Step 3: 运行前端测试**

```bash
cd web && pnpm test 2>&1 | tail -15
```

预期：全部 passed

- [ ] **Step 4: 构建前端**

```bash
pnpm build 2>&1 | tail -10
```

预期：构建成功，无 TypeScript 错误

- [ ] **Step 5: 运行后端快速套件**

```bash
cd .. && python3.11 -m pytest -q -m "not playwright and not android and not slow"
```

预期：全部 passed

- [ ] **Step 6: Commit**

```bash
git add web/src/pages/Devices/Index.tsx web/src/pages/Devices/Index.test.tsx
git commit -m "feat: wire DeviceStreamModal into Devices page"
```

---

## Task 7: 推送到远端

- [ ] **Step 1: 推送**

```bash
git push origin main
```

- [ ] **Step 2: 手动验证（需要已连接 Android 设备）**

1. 启动后端：`python3.11 -m uvicorn --app-dir src autoagent.main:app --reload`
2. 打开 Web UI → Devices 页面
3. 点击在线设备的"查看画面"按钮
4. 确认弹窗出现、画面开始渲染（H264 解码后显示设备画面）
5. 点击画面验证 tap 指令（设备上应有点击响应）
6. 拖动验证 swipe 指令
7. 在文字框输入内容后按 Enter 验证 text 指令
8. 点击"返回"等系统键验证 key 指令
9. 关闭弹窗，确认 screenrecord 进程正常退出（`adb shell ps | grep screenrecord` 应为空）

---

## Self-Review Checklist

- [x] **Spec coverage**: WebSocket 串流 ✓、REST 输入 ✓、tap/swipe/text/key ✓、坐标换算 ✓、serial 注入防护 ✓、重连逻辑 ✓、WebCodecs 不支持提示 ✓、进程终止清理 ✓、动态分辨率 ✓
- [x] **No placeholders**: 所有 step 含完整代码
- [x] **Type consistency**: `DeviceInputRequest` 在 types、api、component 中使用一致；`useDeviceStream` 返回值在 hook 和 Modal 中对齐
