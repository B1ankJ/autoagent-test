import { useCallback, useRef } from 'react'
import { Alert, Button, Modal, Space, Tag } from 'antd'

import { postDeviceInput, useDeviceScreenshot } from '../api/deviceStream'
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
  const { imgRef, src, state, reconnect } = useDeviceScreenshot(serial)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const dragRef = useRef<{ x: number; y: number; t: number } | null>(null)

  // Translate browser-element coordinates to device-pixel coordinates using the
  // <img>'s natural size (the real device resolution).
  const toDeviceCoords = useCallback(
    (img: HTMLImageElement, clientX: number, clientY: number) => {
      const rect = img.getBoundingClientRect()
      const scaleX = (img.naturalWidth || rect.width) / rect.width
      const scaleY = (img.naturalHeight || rect.height) / rect.height
      return {
        x: Math.round((clientX - rect.left) * scaleX),
        y: Math.round((clientY - rect.top) * scaleY),
      }
    },
    [],
  )

  const handleImgMouseDown = useCallback((e: React.MouseEvent<HTMLImageElement>) => {
    e.preventDefault()
    dragRef.current = { x: e.clientX, y: e.clientY, t: Date.now() }
  }, [])

  const handleImgMouseUp = useCallback(
    (e: React.MouseEvent<HTMLImageElement>) => {
      e.preventDefault()
      if (!serial || !imgRef.current || !dragRef.current) return
      const img = imgRef.current
      const start = dragRef.current
      dragRef.current = null

      const dx = e.clientX - start.x
      const dy = e.clientY - start.y
      const dist = Math.sqrt(dx * dx + dy * dy)
      const durationMs = Math.max(100, Math.min(1000, Date.now() - start.t))

      if (dist > 8) {
        const p1 = toDeviceCoords(img, start.x, start.y)
        const p2 = toDeviceCoords(img, e.clientX, e.clientY)
        postDeviceInput(serial, {
          type: 'swipe',
          x1: p1.x,
          y1: p1.y,
          x2: p2.x,
          y2: p2.y,
          duration_ms: durationMs,
        }).catch(console.error)
      } else {
        const p = toDeviceCoords(img, e.clientX, e.clientY)
        postDeviceInput(serial, { type: 'tap', x: p.x, y: p.y }).catch(console.error)
      }
    },
    [serial, imgRef, toDeviceCoords],
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
          {state === 'live' && <Tag color="green">截图轮询中</Tag>}
          {state === 'connecting' && <Tag color="blue">连接中</Tag>}
          {state === 'error' && <Tag color="red">连接失败</Tag>}
        </Space>
      }
      destroyOnClose
    >
      {state === 'error' && (
        <Alert
          type="error"
          message="无法获取设备截图，请检查 adb 是否连接到该设备。"
          style={{ marginBottom: 8 }}
        />
      )}

      <div style={{ display: 'flex', gap: 12 }}>
        <div
          style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}
        >
          <img
            ref={imgRef}
            src={src ?? undefined}
            alt="device screen"
            draggable={false}
            style={{
              width: '100%',
              background: '#000',
              borderRadius: 6,
              cursor: 'crosshair',
              userSelect: 'none',
              minHeight: 300,
              objectFit: 'contain',
            }}
            onMouseDown={handleImgMouseDown}
            onMouseUp={handleImgMouseUp}
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

          {imgRef.current && imgRef.current.naturalWidth > 0 && (
            <div style={{ fontSize: 11, color: '#888' }}>
              <div>分辨率</div>
              <div style={{ color: '#ccc' }}>
                {imgRef.current.naturalWidth} × {imgRef.current.naturalHeight}
              </div>
              <div style={{ marginTop: 6 }}>刷新</div>
              <div style={{ color: '#ccc' }}>~2 FPS</div>
            </div>
          )}
        </div>
      </div>
    </Modal>
  )
}
