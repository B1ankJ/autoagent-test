import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { renderWithProviders } from '../test/test-utils'
import { Sample } from '../types/api'
import { RunningThumbGrid } from './RunningThumbGrid'

const listScreenshots = vi.fn()
const navigate = vi.fn()

vi.mock('../api/screenshots', () => ({
  listScreenshots: (...args: unknown[]) => listScreenshots(...args),
  screenshotUrl: (batchId: string, sampleId: string, name: string, width?: number) =>
    `/api/v1/media/batches/${batchId}/samples/${sampleId}/screenshot/${name}${
      width ? `?w=${width}` : ''
    }`,
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => navigate }
})

function sample(overrides: Partial<Sample>): Sample {
  return {
    id: 's1',
    prompts: ['hi'],
    mode: 'gui_android',
    target_profile: 'p1',
    ...overrides,
  }
}

describe('RunningThumbGrid', () => {
  it('renders nothing when no sample is running', () => {
    renderWithProviders(
      <RunningThumbGrid batchId="b1" samples={[sample({ id: 's1', status: 'done' })]} />,
    )
    expect(screen.queryByText('s1')).not.toBeInTheDocument()
  })

  it('shows a live thumbnail card per running sample and navigates on click', async () => {
    listScreenshots.mockResolvedValue([
      { name: 'after_send_1.jpg', label: 'after_send_1', taken_at: '2026-04-22T00:00:00Z' },
    ])

    renderWithProviders(
      <RunningThumbGrid
        batchId="b1"
        samples={[
          sample({ id: 's1', status: 'running', device_serial: 'ABC123' }),
          sample({ id: 's2', status: 'done' }),
        ]}
      />,
    )

    await waitFor(() => {
      expect(listScreenshots).toHaveBeenCalledWith('b1', 's1')
      expect(listScreenshots).not.toHaveBeenCalledWith('b1', 's2')
    })
    expect(screen.getByText('ABC123')).toBeInTheDocument()

    await userEvent.click(screen.getByText('s1'))
    expect(navigate).toHaveBeenCalledWith('/batches/b1/samples/s1')
  })
})
