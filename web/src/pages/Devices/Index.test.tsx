import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

import { DevicesPage } from './Index'

vi.mock('../../api/devices', () => ({
  useDevices: () => ({
    data: [
      {
        serial: 'emulator-5554',
        label: 'Pixel 8',
        model: 'sdk',
        android_version: '14',
        online: true,
        enabled: true,
      },
    ],
    isLoading: false,
  }),
  useRefreshDevices: () => ({ mutateAsync: vi.fn(), isPending: false }),
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
})
