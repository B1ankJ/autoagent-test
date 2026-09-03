import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'

import { renderWithProviders } from '../test/test-utils'
import type { Device } from '../types/api'
import { DeviceScreenGrid } from './DeviceScreenGrid'

const { httpStreamSerials } = vi.hoisted(() => ({
  httpStreamSerials: [] as (string | null)[],
}))

vi.mock('../api/deviceStream', () => {
  const stubHandle = {
    canvasRef: { current: null },
    state: 'closed' as const,
    latencyMs: null,
    reconnect: vi.fn(),
  }
  return {
    STREAM_QUALITY_PRESETS: { smooth: {}, balanced: {}, sharp: {} },
    useDeviceStream: () => stubHandle,
    useDeviceHttpStream: (serial: string | null) => {
      httpStreamSerials.push(serial)
      return stubHandle
    },
    useDeviceScreenshot: () => ({
      imgRef: { current: null },
      state: 'closed' as const,
      reconnect: vi.fn(),
    }),
    postDeviceInput: vi.fn(),
  }
})

function device(serial: string): Device {
  return {
    serial,
    label: null,
    model: null,
    android_version: null,
    adb_keyboard_installed: null,
    adb_keyboard_enabled: null,
    online: true,
    enabled: true,
    last_seen_at: null,
  }
}

it('pauses (stops streaming) the card whose serial is shown in the full-view modal', () => {
  // Regression: the grid card and the full-view modal both streamed the same
  // serial, fighting over the single per-serial screenrecord — the two views
  // alternated ("small window updates, then big"). The card for the modal's
  // serial must pause (receive a null serial → torn-down stream).
  httpStreamSerials.length = 0
  const devices = [device('d0'), device('d1')]
  renderWithProviders(
    <DeviceScreenGrid devices={devices} onOpenFullView={vi.fn()} pausedSerial="d1" />,
  )
  expect(httpStreamSerials).toContain('d0') // other card still streams
  expect(httpStreamSerials).not.toContain('d1') // paused card never streams its serial
})

it('shows an empty state instead of any cards when there are no devices', () => {
  renderWithProviders(<DeviceScreenGrid devices={[]} onOpenFullView={vi.fn()} />)
  expect(screen.getByText('没有设备')).toBeInTheDocument()
})

it('renders every device with no pagination controls when at or under the page size', () => {
  const devices = Array.from({ length: 8 }, (_, i) => device(`d${i}`))
  renderWithProviders(<DeviceScreenGrid devices={devices} onOpenFullView={vi.fn()} />)

  for (const d of devices) {
    expect(screen.getByText(d.serial)).toBeInTheDocument()
  }
  expect(screen.queryByRole('list')).not.toBeInTheDocument() // antd Pagination renders as a <ul>
})

it('paginates instead of streaming every device at once when there are many', async () => {
  const user = userEvent.setup()
  // 30 devices mirrors the reported production case that reliably timed
  // out when every card opened its own stream simultaneously.
  const devices = Array.from({ length: 30 }, (_, i) => device(`d${i}`))
  renderWithProviders(<DeviceScreenGrid devices={devices} onOpenFullView={vi.fn()} />)

  // First page: only the first 8 devices are mounted (and thus streaming).
  expect(screen.getByText('d0')).toBeInTheDocument()
  expect(screen.getByText('d7')).toBeInTheDocument()
  expect(screen.queryByText('d8')).not.toBeInTheDocument()
  expect(screen.getByText('共 30 台设备')).toBeInTheDocument()

  const pagination = screen.getByText('共 30 台设备').closest('ul') as HTMLElement
  await user.click(within(pagination).getByTitle('2'))

  // Second page: the first page's devices are torn down (not just hidden),
  // so at most one page's worth ever streams concurrently.
  expect(screen.queryByText('d0')).not.toBeInTheDocument()
  expect(screen.getByText('d8')).toBeInTheDocument()
})
