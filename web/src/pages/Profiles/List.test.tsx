import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'

import { renderWithProviders } from '../../test/test-utils'
import type { Device, ProfileSummary } from '../../types/api'
import { ProfileList } from './List'

const profiles: ProfileSummary[] = [
  { name: 'android_bound', platform: 'android', serials: ['dev-1'], avg_duration_ms: 12300 },
  { name: 'android_unbound', platform: 'android', serials: [] },
]

const devices: Device[] = [
  {
    serial: 'dev-1',
    label: 'Pixel 8',
    model: 'sdk',
    android_version: '14',
    adb_keyboard_installed: false,
    adb_keyboard_enabled: false,
    online: true,
    enabled: true,
    last_seen_at: null,
  },
]

vi.mock('../../api/profiles', () => ({
  useProfiles: () => ({ data: profiles, isLoading: false, isError: false, error: null, refetch: vi.fn() }),
  useDeleteProfile: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useSaveProfileDevices: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useInitJob: () => ({ data: undefined }),
  useInitializeDevices: () => ({ mutateAsync: vi.fn(), isPending: false }),
}))

vi.mock('../../api/devices', () => ({
  useDevices: () => ({ data: devices, isLoading: false }),
}))

vi.mock('../../api/deviceStream', () => {
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

it('shows an explicit, irreversible-consequence delete confirmation before removing a profile', async () => {
  renderWithProviders(<ProfileList />)
  await userEvent.click(screen.getByRole('tab', { name: /^Android \(/ }))

  const row = screen.getByText('android_unbound').closest('tr') as HTMLElement
  await userEvent.click(within(row).getByRole('button', { name: /删除/ }))

  expect(screen.getByText('删除配置档 android_unbound?')).toBeInTheDocument()
  expect(screen.getByText(/不可恢复/)).toBeInTheDocument()
})

it('disables 查看画面 for an android profile with no bound devices', async () => {
  renderWithProviders(<ProfileList />)
  await userEvent.click(screen.getByRole('tab', { name: /^Android \(/ }))

  const row = screen.getByText('android_unbound').closest('tr') as HTMLElement
  expect(within(row).getByRole('button', { name: /查看画面/ })).toBeDisabled()
})

it('opens the device screens modal scoped to the profile\'s bound serials', async () => {
  const user = userEvent.setup()
  renderWithProviders(<ProfileList />)
  await user.click(screen.getByRole('tab', { name: /^Android \(/ }))

  const row = screen.getByText('android_bound').closest('tr') as HTMLElement
  await user.click(within(row).getByRole('button', { name: /查看画面/ }))

  const dialog = (await screen.findByText('设备画面 · android_bound')).closest(
    '.ant-modal-content',
  ) as HTMLElement
  expect(within(dialog).getByText('dev-1')).toBeInTheDocument()
})

it('shows the formatted average duration per profile, or "-" when there is none yet', async () => {
  renderWithProviders(<ProfileList />)
  await userEvent.click(screen.getByRole('tab', { name: /^Android \(/ }))

  const boundRow = screen.getByText('android_bound').closest('tr') as HTMLElement
  expect(within(boundRow).getByText('12.3s')).toBeInTheDocument()

  const unboundRow = screen.getByText('android_unbound').closest('tr') as HTMLElement
  expect(within(unboundRow).getByText('-')).toBeInTheDocument()
})
