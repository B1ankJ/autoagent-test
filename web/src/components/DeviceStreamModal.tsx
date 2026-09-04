import { useCallback, useRef, useState } from 'react'
import { Alert, App, Button, Modal, Segmented, Space, Tag } from 'antd'

import {
  postDeviceInput,
  STREAM_QUALITY_PRESETS,
  useDeviceHttpStream,
  useDeviceScreenshot,
  type StreamQualityKey,
} from '../api/deviceStream'
import type { DeviceInputKey } from '../types/api'

interface Props {
  serial: string | null
  onClose: () => void
}

type ViewMode = 'video' | 'snapshot'

// Snapshot mode polls `screencap` this often. screencap grabs the *current*
// framebuffer (~200-300ms stale) with no H264 encoder pipeline, so each frame
// is far fresher than the ~0.5-1.5s screenrecord video — lower frame rate, but
// "tap and see the result" feels much more responsive. Input still goes
// through the fast u2 path either way.
const SNAPSHOT_INTERVAL_MS = 300

const KEY_BUTTONS: Array<{ label: string; keycode: DeviceInputKey['keycode'] }> = [
  { label: '◁ 返回', keycode: 'KEYCODE_BACK' },
  { label: '○ 主页', keycode: 'KEYCODE_HOME' },
  { label: '□ 任务', keycode: 'KEYCODE_APP_SWITCH' },
  { label: 'Enter', keycode: 'KEYCODE_ENTER' },
  { label: 'Del', keycode: 'KEYCODE_DEL' },
]

export function DeviceStreamModal({ serial, onClose }: Props) {
  const [viewMode, setViewMode] = useState<ViewMode>('video')
  // Default to 均衡 (720p, a clean multiple of 16 → no macroblock-crop
  // ambiguity, sharp enough to read). Taps are accurate at any preset now
  // (normalized coords), so this is purely a latency/clarity default — switch
  // to 流畅/极速 for lower latency, or 清晰 for detail.
  const [quality, setQuality] = useState<StreamQualityKey>('balanced')

  // Only one capture streams at a time — pass null to the inactive hook so the
  // two don't fight over the single per-serial screenrecord/screencap.
  const videoSerial = viewMode === 'video' ? serial : null
  const snapSerial = viewMode === 'snapshot' ? serial : null
  const { canvasRef, state, latencyMs, reconnect } = useDeviceHttpStream(
    videoSerial,
    STREAM_QUALITY_PRESETS[quality],
  )
  const {
    imgRef,
    src: snapSrc,
    state: snapState,
    reconnect: snapReconnect,
  } = useDeviceScreenshot(snapSerial, SNAPSHOT_INTERVAL_MS)

  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const dragRef = useRef<{ x: number; y: number; t: number } | null>(null)
  const { message } = App.useApp()

  const activeState = viewMode === 'video' ? state : snapState

  // postDeviceInput calls below used to only .catch(console.error) — if the
  // device drops offline mid-session, taps/swipes/text just silently
  // vanished with the canvas still showing "直播中", giving no indication
  // the input was ever dropped.
  const onInputFailed = useCallback(
    (e: unknown) => message.error(`操作发送失败: ${(e as Error).message}`),
    [message],
  )

  // Maps a click on the display surface to a normalized 0-1 fraction of it —
  // deliberately independent of the surface's pixel resolution (which is the
  // *stream* resolution, not the device's). The backend/u2 scale these to the
  // device's native pixels, so taps stay accurate at any quality preset and on
  // any device. Clamped just under 1 because u2 treats a coord of exactly 1 as
  // an absolute pixel, not a fraction.
  const toNormCoords = useCallback(
    (surface: HTMLElement, clientX: number, clientY: number) => {
      const rect = surface.getBoundingClientRect()
      const clamp = (v: number) => Math.max(0, Math.min(0.9999, v))
      return {
        nx: clamp((clientX - rect.left) / rect.width),
        ny: clamp((clientY - rect.top) / rect.height),
      }
    },
    [],
  )

  const handleSurfaceMouseDown = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement | HTMLImageElement>) => {
      e.preventDefault()
      dragRef.current = { x: e.clientX, y: e.clientY, t: Date.now() }
    },
    [],
  )

  const handleSurfaceMouseUp = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement | HTMLImageElement>) => {
      e.preventDefault()
      const surface = e.currentTarget
      if (!serial || !dragRef.current) return
      const rect = surface.getBoundingClientRect()
      if (rect.width === 0 || rect.height === 0) return // not laid out yet
      const start = dragRef.current
      dragRef.current = null

      const dx = e.clientX - start.x
      const dy = e.clientY - start.y
      const dist = Math.sqrt(dx * dx + dy * dy)
      const durationMs = Math.max(100, Math.min(1000, Date.now() - start.t))

      if (dist > 8) {
        const p1 = toNormCoords(surface, start.x, start.y)
        const p2 = toNormCoords(surface, e.clientX, e.clientY)
        postDeviceInput(serial, {
          type: 'swipe',
          nx1: p1.nx,
          ny1: p1.ny,
          nx2: p2.nx,
          ny2: p2.ny,
          duration_ms: durationMs,
        }).catch(onInputFailed)
      } else {
        const p = toNormCoords(surface, e.clientX, e.clientY)
        postDeviceInput(serial, { type: 'tap', nx: p.nx, ny: p.ny }).catch(onInputFailed)
      }
    },
    [serial, toNormCoords, onInputFailed],
  )

  const handleKeyButton = useCallback(
    (keycode: string) => {
      if (!serial) return
      postDeviceInput(serial, { type: 'key', keycode }).catch(onInputFailed)
    },
    [serial, onInputFailed],
  )

  const handleTextKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        if (!serial || !textareaRef.current) return
        const value = textareaRef.current.value
        if (value) {
          postDeviceInput(serial, { type: 'text', value }).catch(onInputFailed)
          textareaRef.current.value = ''
        }
      }
    },
    [serial, onInputFailed],
  )

  const surfaceStyle: React.CSSProperties = {
    width: '100%',
    background: '#000',
    borderRadius: 6,
    cursor: 'crosshair',
    userSelect: 'none',
    minHeight: 300,
  }

  return (
    <Modal
      open={!!serial}
      onCancel={onClose}
      footer={null}
      width={680}
      title={
        <Space>
          <span>{serial}</span>
          {activeState === 'live' && (
            <Tag color="green">
              直播中
              {viewMode === 'video' && latencyMs != null ? ` ~${latencyMs}ms` : ''}
            </Tag>
          )}
          {activeState === 'connecting' && <Tag color="blue">连接中</Tag>}
          {activeState === 'error' && <Tag color="red">连接失败</Tag>}
          <Segmented
            size="small"
            value={viewMode}
            onChange={(v) => setViewMode(v as ViewMode)}
            options={[
              { label: '视频', value: 'video' },
              { label: '低延迟', value: 'snapshot' },
            ]}
          />
        </Space>
      }
      destroyOnClose
    >
      {viewMode === 'video' && state === 'unsupported' && (
        <Alert
          type="error"
          message="浏览器不支持 WebCodecs，请使用 Chrome 94+ 或 Firefox 130+"
        />
      )}

      <div style={{ display: 'flex', gap: 12 }}>
        <div
          style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}
        >
          {viewMode === 'video' ? (
            <canvas
              ref={canvasRef}
              style={surfaceStyle}
              onMouseDown={handleSurfaceMouseDown}
              onMouseUp={handleSurfaceMouseUp}
              onDragStart={(e) => e.preventDefault()}
            />
          ) : (
            <img
              ref={imgRef}
              src={snapSrc ?? undefined}
              alt="device screen"
              draggable={false}
              style={surfaceStyle}
              onMouseDown={handleSurfaceMouseDown}
              onMouseUp={handleSurfaceMouseUp}
              onDragStart={(e) => e.preventDefault()}
            />
          )}
          <Space>
            {KEY_BUTTONS.map((btn) => (
              <Button key={btn.keycode} size="small" onClick={() => handleKeyButton(btn.keycode)}>
                {btn.label}
              </Button>
            ))}
          </Space>
          {viewMode === 'video' && (
            <Segmented
              size="small"
              value={quality}
              onChange={(v) => setQuality(v as StreamQualityKey)}
              options={[
                { label: '极速', value: 'ultra' },
                { label: '流畅', value: 'smooth' },
                { label: '均衡', value: 'balanced' },
                { label: '清晰', value: 'sharp' },
              ]}
            />
          )}
          {activeState === 'error' && (
            <Button onClick={viewMode === 'video' ? reconnect : snapReconnect}>重新连接</Button>
          )}
        </div>

        <div style={{ width: 140, display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div>
            <div style={{ fontSize: 11, color: '#888', marginBottom: 4 }}>文字输入</div>
            <textarea
              ref={textareaRef}
              rows={3}
              placeholder="输入后按 Enter 发送…"
              style={{
                width: '100%',
                resize: 'none',
                boxSizing: 'border-box',
                padding: '4px 6px',
                borderRadius: 4,
                border: '1px solid #d9d9d9',
                fontSize: 12,
              }}
              onKeyDown={handleTextKeyDown}
            />
            <div style={{ fontSize: 10, color: '#bbb' }}>Enter 发送 · Shift+Enter 换行</div>
          </div>

          <div style={{ fontSize: 11, color: '#888' }}>
            <div>模式</div>
            <div style={{ color: '#ccc' }}>
              {viewMode === 'video' ? '视频流 (H264)' : '低延迟截图'}
            </div>
            {viewMode === 'video' && latencyMs != null && (
              <>
                <div style={{ marginTop: 6 }}>延迟</div>
                <div style={{ color: latencyMs < 200 ? '#4caf50' : '#ff9800' }}>{latencyMs}ms</div>
              </>
            )}
          </div>
        </div>
      </div>
    </Modal>
  )
}
