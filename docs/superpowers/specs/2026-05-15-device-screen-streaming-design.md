# Device Screen Streaming Design

**Date:** 2026-05-15
**Status:** Draft

## Overview

在 Devices 页面为每台 Android 设备新增"查看画面"功能：点击后弹出模态框，实时显示设备屏幕画面（H264 via WebSocket + WebCodecs），并支持点击、滑动、文字输入三种交互方式，指令通过 REST 接口下发至 `adb input`。

## Goals

- 延迟 ≤ 200ms（局域网云手机）
- 支持完整交互：tap / swipe / text / system keys
- 不影响现有设备管理功能和正在运行的批量测试
- 一次只能对一台设备开启弹窗（避免多路 screenrecord 资源竞争）

## Non-Goals

- 多设备同时监控（不做多窗口平铺）
- 录屏保存
- WebRTC / MJPEG fallback（暂不做，云手机确认支持 H264 后实施）
- Safari / 旧浏览器兼容（WebCodecs 要求 Chrome 94+ / Firefox 130+）

## Architecture

```
Android Device
  └─ adb exec-out screenrecord --output-format=h264 --size 720x1280 -
        │  H264 裸流（stdout）
        ▼
Backend (FastAPI)
  ├─ WS  GET /api/v1/devices/{serial}/stream
  │       • 启动 screenrecord 子进程（asyncio subprocess）
  │       • 按 chunk 读取 stdout，逐块推送 binary WS frame
  │       • WS 断开时 terminate 子进程
  └─ POST /api/v1/devices/{serial}/input
          • body: {type, ...params}
          • 调用对应 adb input 命令
          • 返回 204

Frontend (React)
  └─ DeviceStreamModal
       ├─ useDeviceStream(serial) hook
       │     • WebSocket → binary frames buffer
       │     • NAL 单元分割（起始码 00 00 00 01）
       │     • SPS/PPS → VideoDecoder.configure()
       │     • I/P 帧 → decoder.decode(EncodedVideoChunk)
       │     • VideoFrame → canvas.drawImage()
       ├─ <canvas> 渲染区域
       │     • click → tap（坐标换算）
       │     • mousedown+mousemove+mouseup → swipe（移动 > 8px 判定为滑动）
       ├─ 右侧边栏
       │     • textarea：Enter 发送 text，Shift+Enter 换行
       │     • 快捷键按钮：返回 / 主页 / 任务 / Enter / Del
       └─ 状态栏：延迟估算、分辨率、在线状态
```

## Backend

### WS /api/v1/devices/{serial}/stream

- **鉴权**：复用现有 Bearer token（URL query param `?token=...`，WebSocket 不支持自定义 header）
- **子进程**：`asyncio.create_subprocess_exec("adb", "-s", serial, "exec-out", "screenrecord", "--output-format=h264", "--size", "720x1280", "-", stdout=PIPE)`
- **推流**：循环 `await proc.stdout.read(65536)`，非空则 `await ws.send_bytes(chunk)`
- **生命周期**：WS 关闭（正常/异常）时 `proc.terminate()`，等待最多 3s 后 `proc.kill()`
- **每 serial 限一路**：用模块级 `dict[str, Process]` 记录活跃进程，新连接到来时先终止旧进程
- **screenrecord 不支持时**：子进程 stderr 含 "unknown option" 或立即退出，后端发 JSON 错误帧 `{"error": "screenrecord_unsupported"}` 后关闭 WS

### POST /api/v1/devices/{serial}/input

请求体 schema（discriminated union by `type`）：

```json
{"type": "tap",   "x": 360, "y": 640}
{"type": "swipe", "x1": 100, "y1": 500, "x2": 100, "y2": 200, "duration_ms": 300}
{"type": "text",  "value": "hello world"}
{"type": "key",   "keycode": "KEYCODE_BACK"}
```

对应 adb 命令：
- tap：`adb -s {serial} shell input tap {x} {y}`
- swipe：`adb -s {serial} shell input swipe {x1} {y1} {x2} {y2} {duration_ms}`
- text：`adb -s {serial} shell input text '{escaped}'`（特殊字符需 shell 转义）
- key：`adb -s {serial} shell input keyevent {keycode}`

返回 `204 No Content`；adb 错误返回 `502`。

## Frontend

### useDeviceStream(serial)

```ts
// 状态
type StreamState = "connecting" | "live" | "error" | "unsupported" | "closed"

// 返回
{ canvasRef, state, latencyMs, resolution, reconnect }
```

**WebCodecs 解码流程：**

1. 收到首个 binary frame，累积到 buffer
2. 扫描起始码 `00 00 00 01`，分割 NAL 单元
3. NAL type=7（SPS）+ type=8（PPS）到齐后调用 `VideoDecoder.configure({ codec: "avc1.42E01E", ... })`
4. NAL type=5（IDR）或 type=1（non-IDR）封装为 `EncodedVideoChunk` 送入 `decoder.decode()`
5. `decoder.output` 回调中 `ctx.drawImage(frame, 0, 0)`，`frame.close()`

**重连策略：** WS 意外断开后，等待 2s 自动重连，最多 3 次；3 次失败后 state → "error"，显示"重新连接"按钮。

### DeviceStreamModal

- **打开方式**：Devices 表格每行操作列新增"查看画面"按钮；同一时刻只能开一个弹窗（用全局 state 控制 serial）
- **canvas 交互**：
  - click：`(e.offsetX / canvas.clientWidth * deviceWidth, ...)` 换算后 POST tap
  - mousedown → mousemove（记录轨迹）→ mouseup：若总位移 > 8px，POST swipe（取 mousedown 和 mouseup 坐标，duration_ms = 鼠标按下时长 clamp 到 100-1000ms）；否则 POST tap
  - 拖动时阻止默认行为防止文字选中
- **文字输入**：textarea `keydown` 监听，Enter（非 Shift）时 POST text，清空 textarea
- **快捷键按钮**：POST key，keycode 映射：返回=KEYCODE_BACK，主页=KEYCODE_HOME，任务=KEYCODE_APP_SWITCH，Enter=KEYCODE_ENTER，Del=KEYCODE_DEL
- **延迟估算**：`EncodedVideoChunk.timestamp`（screenrecord 时间戳）与 `performance.now()` 差值，滚动平均最近 30 帧

### 新增文件

```
src/autoagent/api/device_stream.py          # WS + input 端点
src/autoagent/executors/device_input.py     # adb input 命令封装
web/src/api/deviceStream.ts                 # WS hook + input API
web/src/components/DeviceStreamModal.tsx    # 弹窗组件
```

### 修改文件

```
src/autoagent/main.py                       # 注册 device_stream router
web/src/pages/Devices/Index.tsx             # 添加"查看画面"按钮
web/src/types/api.ts                        # DeviceInputRequest 类型
```

## Error Handling

| 场景 | 处理方式 |
|---|---|
| screenrecord 不支持 H264 | 后端发 JSON 错误帧，前端显示"该设备不支持 H264 串流" |
| WebCodecs 不支持 | 前端检测 `'VideoDecoder' in window`，显示"浏览器不支持，请使用 Chrome 94+" |
| WS 意外断开 | 自动重连 3 次，失败后显示错误 + 重连按钮 |
| adb input 失败 | POST /input 返回 502，前端 toast 提示"操作失败" |
| 设备离线 | screenrecord 进程立即退出，触发 WS 关闭，前端进入重连流程 |

## Testing

**后端单元测试（`tests/unit/test_device_stream.py`）：**
- `/input` 端点各 type 的 adb 命令生成正确性
- text 输入中特殊字符的 shell 转义
- 非法 serial 字符拒绝（防命令注入）
- WS 端点用 mock subprocess 验证推流和断连清理逻辑

**前端测试：**
- WebCodecs 解码路径依赖浏览器 API，不写单元测试
- DeviceStreamModal 渲染和按钮交互用 Vitest + RTL mock WebSocket

## Security

- serial 参数做白名单校验（只允许 `[a-zA-Z0-9._:+-]`），防止 shell 注入
- text input 中单引号、反斜杠做转义
- WS 端点复用现有 Bearer 鉴权，token 通过 URL query param 传递

## Open Questions

- 云手机是否支持 `screenrecord --output-format=h264`？需在 `192.168.235.240:5555` 上验证后再实施。验证命令：`adb -s 192.168.235.240:5555 shell screenrecord --output-format=h264 --time-limit=3 /sdcard/test.mp4 && echo ok`
- `--size` 参数应动态读取设备分辨率（`adb shell wm size`）还是固定 720x1280？建议动态读取后按比例缩放到宽度 720。
