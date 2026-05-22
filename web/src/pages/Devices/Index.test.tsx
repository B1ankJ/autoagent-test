import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

import { DevicesPage } from './Index'

const mutateAsync = vi.fn()

vi.mock('../../api/deviceStream', () => ({
  useDeviceStream: () => ({
    canvasRef: { current: null },
    state: 'closed',
    latencyMs: null,
    reconnect: vi.fn(),
  }),
  postDeviceInput: vi.fn(),
}))

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
    ],
    isLoading: false,
  }),
  useRefreshDevices: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useInstallAdbKeyboard: () => ({ mutateAsync, isPending: false }),
  useEnableIme: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDisableIme: () => ({ mutateAsync: vi.fn(), isPending: false }),
}))

it('renders device rows', () => {
  render(
    <MemoryRouter>
      <QueryClientProvider client={new QueryClient()}>
        <DevicesPage />
      </QueryClientProvider>
    </MemoryRouter>,
  )
  expect(screen.getByText('emulator-5554')).toBeInTheDocument()
  expect(screen.getByText('Pixel 8')).toBeInTheDocument()
  expect(screen.getByText('not installed')).toBeInTheDocument()
})

it('renders 查看画面 button for online device', () => {
  render(
    <MemoryRouter>
      <QueryClientProvider client={new QueryClient()}>
        <DevicesPage />
      </QueryClientProvider>
    </MemoryRouter>,
  )
  expect(screen.getByText('查看画面')).toBeInTheDocument()
})

it('installs adb keyboard from device table action', async () => {
  const user = userEvent.setup()
  render(
    <MemoryRouter>
      <QueryClientProvider client={new QueryClient()}>
        <DevicesPage />
      </QueryClientProvider>
    </MemoryRouter>,
  )

  await user.click(screen.getByRole('button', { name: 'Install ADB Keyboard' }))

  expect(mutateAsync).toHaveBeenCalledWith('emulator-5554')
})
