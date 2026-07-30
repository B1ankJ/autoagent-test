import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'

import { renderWithProviders } from '../test/test-utils'
import { DeviceInitModal } from './DeviceInitModal'

const { mockUseInitJob, refetchMock } = vi.hoisted(() => ({
  mockUseInitJob: vi.fn(),
  refetchMock: vi.fn(),
}))

vi.mock('../api/profiles', () => ({
  useInitJob: mockUseInitJob,
  useInitializeDevices: () => ({ mutateAsync: vi.fn(), isPending: false }),
}))

beforeEach(() => {
  refetchMock.mockReset()
  mockUseInitJob.mockReturnValue({ data: undefined, isError: false })
})

it('shows an error alert with a retry button when init-job polling fails', async () => {
  // Regression: useInitJob's isError was never checked — if polling failed
  // (backend restart drops the in-memory job, network blip after React
  // Query's retries are exhausted), the modal just kept showing the last
  // known per-device tags forever with no indication the status feed died.
  mockUseInitJob.mockReturnValue({
    data: { finished: false, devices: [] },
    isError: true,
    error: new Error('job not found'),
    refetch: refetchMock,
  })

  renderWithProviders(
    <DeviceInitModal profileName="p1" serials={['emulator-5554']} onClose={vi.fn()} />,
  )

  expect(screen.getByText('状态查询失败,以上进度可能已过期')).toBeInTheDocument()
  expect(screen.getByText('job not found')).toBeInTheDocument()

  await userEvent.click(screen.getByRole('button', { name: /重\s?试/ }))
  expect(refetchMock).toHaveBeenCalled()
})
