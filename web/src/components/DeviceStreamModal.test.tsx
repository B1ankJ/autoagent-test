import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'

import { renderWithProviders } from '../test/test-utils'
import { DeviceStreamModal } from './DeviceStreamModal'

const { postDeviceInputMock } = vi.hoisted(() => ({ postDeviceInputMock: vi.fn() }))

vi.mock('../api/deviceStream', () => ({
  postDeviceInput: postDeviceInputMock,
  STREAM_QUALITY_PRESETS: { smooth: {}, balanced: {}, sharp: {} },
  useDeviceHttpStream: () => ({
    canvasRef: { current: null },
    state: 'live' as const,
    latencyMs: 40,
    reconnect: vi.fn(),
  }),
}))

beforeEach(() => {
  postDeviceInputMock.mockReset()
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
