import { useCallback, useRef } from 'react'
import { Alert, Button, Modal, Space, Tag } from 'antd'

import { postDeviceInput, useDeviceStream } from '../api/deviceStream'
import type { DeviceInputKey } from '../types/api'

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

  const handleCanvasMouseDown = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    e.preventDefault()
    dragRef.current = { x: e.clientX, y: e.clientY, t: Date.now() }
  }, [])

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
        postDeviceInput(serial, {
          type: 'swipe',
          x1: p1.x,
          y1: p1.y,
          x2: p2.x,
          y2: p2.y,
          duration_ms: durationMs,
        }).catch(console.error)
      } else {
        const p = toDeviceCoords(canvas, e.clientX, e.clientY)
        postDeviceInput(serial, { type: 'tap', x: p.x, y: p.y }).catch(console.error)
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
          {state === 'live' && (
            <Tag color="green">直播中{latencyMs != null ? ` ~${latencyMs}ms` : ''}</Tag>
          )}
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
        <div
          style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}
        >
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
          {state === 'error' && <Button onClick={reconnect}>重新连接</Button>}
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

          {canvasRef.current && (
            <div style={{ fontSize: 11, color: '#888' }}>
              <div>分辨率</div>
              <div style={{ color: '#ccc' }}>
                {canvasRef.current.width} × {canvasRef.current.height}
              </div>
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
