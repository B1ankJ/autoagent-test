import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'

import { renderWithProviders } from '../../test/test-utils'
import { DevicesPage } from './Index'

const mutateAsync = vi.fn()
const connectMutateAsync = vi.fn()
const disconnectMutateAsync = vi.fn()
const deleteMutateAsync = vi.fn()

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

vi.mock('../../api/devices', () => ({
  useDevices: () => ({
    data: [
      {
        serial: 'emulator-5554',
        label: 'Pixel 8',
        model: 'sdk',
        android_version: '14',
        adb_keyboard_installed: false,
        adb_keyboard_enabled: false,
        online: true,
        enabled: true,
      },
      {
        serial: 'emulator-5556',
        label: 'Pixel 9',
        model: 'sdk2',
        android_version: '15',
        adb_keyboard_installed: false,
        adb_keyboard_enabled: false,
        online: false,
        enabled: false,
      },
    ],
    isLoading: false,
  }),
  useRefreshDevices: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useInstallAdbKeyboard: () => ({ mutateAsync, isPending: false }),
  useEnableIme: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDisableIme: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useConnectDevice: () => ({ mutateAsync: connectMutateAsync, isPending: false }),
  useDisconnectDevice: () => ({ mutateAsync: disconnectMutateAsync, isPending: false }),
  useUpdateDeviceLabel: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteDevice: () => ({ mutateAsync: deleteMutateAsync, isPending: false }),
}))

function renderPage() {
  return renderWithProviders(<DevicesPage />)
}

function rowFor(serial: string) {
  return screen.getByText(serial).closest('tr') as HTMLElement
}

beforeEach(() => {
  mutateAsync.mockClear()
  connectMutateAsync.mockClear()
  disconnectMutateAsync.mockClear()
  deleteMutateAsync.mockClear()
})

it('renders device rows', () => {
  renderPage()
  expect(screen.getByText('emulator-5554')).toBeInTheDocument()
  expect(screen.getByText('Pixel 8')).toBeInTheDocument()
  expect(screen.getAllByText('not installed')).toHaveLength(2)
})

it('renders 查看画面 button, disabled for the offline device', () => {
  renderPage()
  const onlineRow = within(rowFor('emulator-5554'))
  const offlineRow = within(rowFor('emulator-5556'))
  expect(onlineRow.getByRole('button', { name: '查看画面' })).toBeEnabled()
  expect(offlineRow.getByRole('button', { name: '查看画面' })).toBeDisabled()
})

it('installs adb keyboard from device table action', async () => {
  const user = userEvent.setup()
  renderPage()

  const onlineRow = within(rowFor('emulator-5554'))
  await user.click(onlineRow.getByRole('button', { name: 'Install ADB Keyboard' }))

  expect(mutateAsync).toHaveBeenCalledWith('emulator-5554')
})

it('toggles a single device via the per-row 启用/禁用 button', async () => {
  const user = userEvent.setup()
  renderPage()

  const enabledRow = within(rowFor('emulator-5554'))
  await user.click(enabledRow.getByRole('button', { name: /禁用/ }))
  expect(disconnectMutateAsync).toHaveBeenCalledWith('emulator-5554')

  const disabledRow = within(rowFor('emulator-5556'))
  await user.click(disabledRow.getByRole('button', { name: /启用/ }))
  expect(connectMutateAsync).toHaveBeenCalledWith('emulator-5556')
})

it('bulk-enables selected devices via the checkbox toolbar', async () => {
  const user = userEvent.setup()
  renderPage()

  // checkboxes[0] is the header "select all"; row checkboxes follow.
  const checkboxes = screen.getAllByRole('checkbox')
  await user.click(checkboxes[1])
  await user.click(checkboxes[2])

  // Icon-only buttons pick up the icon's own accessible name too (e.g.
  // "play-circle 批量启用"), so match by substring, not exact text.
  await user.click(screen.getByRole('button', { name: /批量启用/ }))

  expect(connectMutateAsync).toHaveBeenCalledWith('emulator-5554')
  expect(connectMutateAsync).toHaveBeenCalledWith('emulator-5556')
})

it('bulk-deletes selected devices after confirmation', async () => {
  const user = userEvent.setup()
  renderPage()

  const checkboxes = screen.getAllByRole('checkbox')
  await user.click(checkboxes[0]) // select-all

  await user.click(screen.getByRole('button', { name: /批量删除/ }))
  // AntD Button inserts a mid-word space between two-character CJK labels
  // ("删除" renders as "删 除"); scope to the popup so this doesn't also
  // match the "批量删除" trigger button (which contains "删除" too).
  const popup = await screen.findByRole('tooltip')
  await user.click(within(popup).getByRole('button', { name: /删\s?除/ }))

  expect(deleteMutateAsync).toHaveBeenCalledWith('emulator-5554')
  expect(deleteMutateAsync).toHaveBeenCalledWith('emulator-5556')
})
