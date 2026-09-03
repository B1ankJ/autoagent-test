import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'

import { renderWithProviders } from '../test/test-utils'
import { DeviceStreamModal } from './DeviceStreamModal'

const { postDeviceInputMock, videoSerials, snapSerials } = vi.hoisted(() => ({
  postDeviceInputMock: vi.fn(),
  videoSerials: [] as (string | null)[],
  snapSerials: [] as (string | null)[],
}))

vi.mock('../api/deviceStream', () => ({
  postDeviceInput: postDeviceInputMock,
  STREAM_QUALITY_PRESETS: { ultra: {}, smooth: {}, balanced: {}, sharp: {} },
  useDeviceHttpStream: (serial: string | null) => {
    videoSerials.push(serial)
    return { canvasRef: { current: null }, state: 'live' as const, latencyMs: 40, reconnect: vi.fn() }
  },
  useDeviceScreenshot: (serial: string | null) => {
    snapSerials.push(serial)
    return { imgRef: { current: null }, src: null, state: 'live' as const, reconnect: vi.fn() }
  },
}))

beforeEach(() => {
  postDeviceInputMock.mockReset()
  videoSerials.length = 0
  snapSerials.length = 0
})

it('shows an error toast instead of silently dropping input when the device is unreachable', async () => {
  // Regression: postDeviceInput calls only did .catch(console.error) — a
  // device that went offline mid-session made taps/swipes/keys/text just
  // silently vanish, with the canvas still showing "直播中" and no
  // indication anything failed.
  postDeviceInputMock.mockRejectedValueOnce(new Error('device offline'))
  const user = userEvent.setup()
  renderWithProviders(<DeviceStreamModal serial="emulator-5554" onClose={vi.fn()} />)

  await user.click(screen.getByRole('button', { name: /返回/ }))

  expect(await screen.findByText('操作发送失败: device offline')).toBeInTheDocument()
})

it('streams only the active mode: video by default, screencap after switching to 低延迟', async () => {
  const user = userEvent.setup()
  renderWithProviders(<DeviceStreamModal serial="emulator-5554" onClose={vi.fn()} />)

  // Default video mode: the H264 stream runs, screencap is torn down (null).
  expect(videoSerials).toContain('emulator-5554')
  expect(snapSerials.every((s) => s === null)).toBe(true)

  videoSerials.length = 0
  snapSerials.length = 0
  await user.click(screen.getByText('低延迟'))

  // Now screencap runs and the video stream is torn down (null) — so the two
  // captures never fight over the one per-serial pipeline.
  expect(snapSerials).toContain('emulator-5554')
  expect(videoSerials.every((s) => s === null)).toBe(true)
})
