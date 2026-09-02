import { ExpandOutlined } from '@ant-design/icons'
import { Button, Card, Space, Tag, Typography } from 'antd'
import { useState } from 'react'

import { STREAM_QUALITY_PRESETS, useDeviceHttpStream } from '../api/deviceStream'
import { usePageVisible } from '../hooks/usePageVisible'
import type { Device } from '../types/api'

interface Props {
  device: Device
  onOpenFullView: (serial: string) => void
}

/**
 * Compact streaming tile for the Devices "cards" view. Each card opens its
 * own websocket via useDeviceHttpStream so N cards = N decoders running in
 * parallel — fine for 4–8 devices on a desktop browser, may stutter beyond
 * that. Streaming starts on mount when the device is online; offline rows
 * render a placeholder so the grid stays balanced.
 */
export function DeviceStreamCard({ device, onOpenFullView }: Props) {
  // Stream only when online AND the tab is visible — passing null tears the
  // stream down, so a hidden tab stops burning CPU/adb bandwidth on N decoders.
  const visible = usePageVisible()
  const serial = device.online && visible ? device.serial : null
  // Grid tiles run N decoders + N screenrecord processes in parallel, so use
  // the low-bitrate/low-res 'smooth' preset here to keep many streams fluid.
  const { canvasRef, state, latencyMs, reconnect } = useDeviceHttpStream(
    serial,
    STREAM_QUALITY_PRESETS.smooth,
  )
  const [hovered, setHovered] = useState(false)

  const title = device.label || device.model || device.serial
  const subtitle = device.label || device.model ? device.serial : null

  return (
    <Card
      size="small"
      hoverable
      bodyStyle={{ padding: 8 }}
      title={
        <Space size={6}>
          <Typography.Text strong style={{ fontSize: 13 }}>
            {title}
          </Typography.Text>
          {subtitle ? (
            <Typography.Text type="secondary" style={{ fontSize: 11 }} className="aa-mono">
              {subtitle}
            </Typography.Text>
          ) : null}
        </Space>
      }
      extra={
        <Space size={4}>
          {!device.online ? (
            <Tag color="default">离线</Tag>
          ) : state === 'live' ? (
            <Tag color="green">
              直播{latencyMs != null ? ` ${latencyMs}ms` : ''}
            </Tag>
          ) : state === 'connecting' ? (
            <Tag color="blue">连接中</Tag>
          ) : state === 'error' ? (
            <Tag color="red">失败</Tag>
          ) : state === 'unsupported' ? (
            <Tag color="orange">不支持</Tag>
          ) : null}
          <Button
            size="small"
            type="text"
            icon={<ExpandOutlined />}
            title="打开完整控制窗口"
            onClick={() => onOpenFullView(device.serial)}
          />
        </Space>
      }
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {device.online ? (
        <div style={{ position: 'relative' }}>
          <canvas
            ref={canvasRef}
            style={{
              width: '100%',
              background: '#000',
              borderRadius: 4,
              display: 'block',
              minHeight: 240,
              cursor: 'pointer',
            }}
            onClick={() => onOpenFullView(device.serial)}
          />
          {hovered && state === 'error' ? (
            <Button
              size="small"
              style={{ position: 'absolute', top: 8, right: 8 }}
              onClick={reconnect}
            >
              重连
            </Button>
          ) : null}
        </div>
      ) : (
        <div
          style={{
            background: '#1a1a1a',
            borderRadius: 4,
            minHeight: 240,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#666',
            fontSize: 12,
          }}
        >
          设备离线
        </div>
      )}
    </Card>
  )
}
