import { screen } from '@testing-library/react'
import { vi } from 'vitest'

import { renderWithProviders } from '../test/test-utils'
import type { Device } from '../types/api'
import { ProfileDeviceScreensModal } from './ProfileDeviceScreensModal'

vi.mock('../api/deviceStream', () => {
  const stubHandle = {
    canvasRef: { current: null },
    state: 'closed' as const,
    latencyMs: null,
    reconnect: vi.fn(),
  }
  return {
    useDeviceStream: () => stubHandle,
    useDeviceHttpStream: () => stubHandle,
    useDeviceScreenshot: () => ({
      imgRef: { current: null },
      state: 'closed' as const,
      reconnect: vi.fn(),
    }),
    postDeviceInput: vi.fn(),
  }
})

const devices: Device[] = [
  {
    serial: 'bound-1',
    label: 'Pixel 8',
    model: 'sdk',
    android_version: '14',
    adb_keyboard_installed: false,
    adb_keyboard_enabled: false,
    online: true,
    enabled: true,
    last_seen_at: null,
  },
  {
    serial: 'unbound-1',
    label: null,
    model: null,
    android_version: null,
    adb_keyboard_installed: null,
    adb_keyboard_enabled: null,
    online: true,
    enabled: true,
    last_seen_at: null,
  },
]

vi.mock('../api/devices', () => ({
  useDevices: () => ({ data: devices, isLoading: false }),
}))

it('only shows devices bound to the profile, not every known device', () => {
  renderWithProviders(
    <ProfileDeviceScreensModal
      profileName="android_profile"
      serials={['bound-1']}
      onClose={vi.fn()}
    />,
  )

  expect(screen.getByText('bound-1')).toBeInTheDocument()
  expect(screen.queryByText('unbound-1')).not.toBeInTheDocument()
})

it('warns about bound serials that are missing from the known device list', () => {
  renderWithProviders(
    <ProfileDeviceScreensModal
      profileName="android_profile"
      serials={['bound-1', 'gone-forever']}
      onClose={vi.fn()}
    />,
  )

  expect(screen.getByText(/1 台绑定设备当前不在 Devices 列表中/)).toBeInTheDocument()
})

it('renders nothing when closed', () => {
  renderWithProviders(
    <ProfileDeviceScreensModal profileName={null} serials={[]} onClose={vi.fn()} />,
  )
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})
