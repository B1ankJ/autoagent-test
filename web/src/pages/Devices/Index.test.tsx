import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'

import { renderWithProviders } from '../../test/test-utils'
import { DevicesPage } from './Index'

const mutateAsync = vi.fn()
const connectMutateAsync = vi.fn()
const disconnectMutateAsync = vi.fn()
const deleteMutateAsync = vi.fn()

const { mockUseDeviceSessions, mockReleaseSession } = vi.hoisted(() => ({
  mockUseDeviceSessions: vi.fn(),
  mockReleaseSession: vi.fn(),
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
  useDeviceSessions: mockUseDeviceSessions,
  useReleaseDeviceSession: () => ({ mutateAsync: mockReleaseSession, isPending: false }),
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
  mockReleaseSession.mockClear()
  mockUseDeviceSessions.mockReturnValue({ data: [], isLoading: false })
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

it('keeps only the failed device selected after a partial bulk-enable failure', async () => {
  // Regression: runBulk used to unconditionally clear the whole selection
  // after Promise.allSettled, even on partial failure — the only feedback
  // was an aggregate "N succeeded, M failed" toast with no way to tell
  // which device(s) failed short of manually comparing, so retrying meant
  // re-picking from scratch. Now only the failed ones stay selected.
  connectMutateAsync.mockImplementationOnce(() => Promise.resolve())
  connectMutateAsync.mockImplementationOnce(() => Promise.reject(new Error('boom')))
  const user = userEvent.setup()
  renderPage()

  const checkboxes = screen.getAllByRole('checkbox')
  await user.click(checkboxes[1]) // emulator-5554
  await user.click(checkboxes[2]) // emulator-5556

  await user.click(screen.getByRole('button', { name: /批量启用/ }))

  await waitFor(() => expect(connectMutateAsync).toHaveBeenCalledTimes(2))
  await waitFor(() => {
    expect((checkboxes[1] as HTMLInputElement).checked).toBe(false)
    expect((checkboxes[2] as HTMLInputElement).checked).toBe(true)
  })
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

// The session-occupancy panel now lives behind a 会话占用 button + Popover
// (mirrors Batches List's 筛选 pattern) instead of an always-rendered card,
// so every test below opens it first.
async function openSessionsPopover(user: ReturnType<typeof userEvent.setup>) {
  // Icon-only-prefixed buttons pick up the icon's own accessible name too
  // (e.g. "lock 会话占用"), same as the 批量启用 case below — match by substring.
  await user.click(screen.getByRole('button', { name: /会话占用/ }))
}

it('shows a message when no session is currently occupying a device', async () => {
  const user = userEvent.setup()
  renderPage()
  await openSessionsPopover(user)
  expect(await screen.findByText('当前没有正在占用设备的多轮对话')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '一键释放全部' })).toBeDisabled()
})

it('releases every active session via 一键释放全部', async () => {
  const user = userEvent.setup()
  mockUseDeviceSessions.mockReturnValue({
    data: [
      { session_id: 'conv-1', serial: 'emulator-5554', expires_in_sec: 600 },
      { session_id: 'conv-2', serial: 'emulator-5556', expires_in_sec: 600 },
    ],
    isLoading: false,
  })
  renderPage()
  await openSessionsPopover(user)

  const trigger = await screen.findByRole('button', { name: '一键释放全部' })
  expect(trigger).toBeEnabled()
  await user.click(trigger)
  // "全部释放" (the Popconfirm's okText) is unique in the document, so no
  // extra scoping is needed to find its confirm button.
  await user.click(await screen.findByRole('button', { name: '全部释放' }))

  expect(mockReleaseSession).toHaveBeenCalledWith('conv-1')
  expect(mockReleaseSession).toHaveBeenCalledWith('conv-2')
})

it('renders an active session pin and releases it after confirmation', async () => {
  const user = userEvent.setup()
  mockUseDeviceSessions.mockReturnValue({
    data: [{ session_id: 'conv-1', serial: 'emulator-5554', expires_in_sec: 605 }],
    isLoading: false,
  })
  renderPage()
  await openSessionsPopover(user)

  expect(await screen.findByText('conv-1')).toBeInTheDocument()
  // Friendly label (from the mocked device list) rather than the bare serial.
  expect(screen.getByText('Pixel 8 (emulator-5554)')).toBeInTheDocument()
  expect(screen.getByText('10:05')).toBeInTheDocument()

  // Scope to the row's own button: the page also has a 一键释放全部 button
  // whose name contains "释放" too, and (like 批量删除 below) AntD inserts a
  // mid-word space in the two-character "释放" label ("释 放").
  const row = screen.getByText('conv-1').closest('tr') as HTMLElement
  await user.click(within(row).getByRole('button', { name: /释\s?放/ }))
  // Two popups are now open (the outer 会话占用 Popover + this row's
  // Popconfirm) — both expose role="tooltip", so scope to whichever
  // mounted last rather than assuming there's only one.
  const tooltips = await screen.findAllByRole('tooltip')
  await user.click(within(tooltips[tooltips.length - 1]!).getByRole('button', { name: /释\s?放/ }))

  expect(mockReleaseSession).toHaveBeenCalledWith('conv-1')
})

it('paginates the session list instead of rendering every row at once', async () => {
  const user = userEvent.setup()
  const data = Array.from({ length: 8 }, (_, i) => ({
    session_id: `conv-${i}`,
    serial: 'emulator-5554',
    expires_in_sec: 600,
  }))
  mockUseDeviceSessions.mockReturnValue({ data, isLoading: false })
  renderPage()
  await openSessionsPopover(user)

  expect(await screen.findByText('conv-0')).toBeInTheDocument()
  expect(screen.getByText('conv-5')).toBeInTheDocument()
  expect(screen.queryByText('conv-6')).not.toBeInTheDocument()

  await user.click(screen.getByTitle('2'))

  expect(await screen.findByText('conv-6')).toBeInTheDocument()
  expect(screen.getByText('conv-7')).toBeInTheDocument()
  expect(screen.queryByText('conv-0')).not.toBeInTheDocument()
})

it('applies ellipsis truncation styling to the occupied-device tag so a long label cannot overflow into 剩余时间', async () => {
  const user = userEvent.setup()
  mockUseDeviceSessions.mockReturnValue({
    data: [{ session_id: 'conv-1', serial: 'emulator-5554', expires_in_sec: 605 }],
    isLoading: false,
  })
  renderPage()
  await openSessionsPopover(user)

  const tag = await screen.findByText('Pixel 8 (emulator-5554)')
  expect(tag).toHaveStyle({ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' })
  expect(screen.getByText('10:05')).toBeInTheDocument()
})
