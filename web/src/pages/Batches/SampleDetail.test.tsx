import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { Route, Routes } from 'react-router-dom'
import { renderWithProviders } from '../../test/test-utils'
import { SampleDetail } from './SampleDetail'

const useBatchStream = vi.fn()
const listScreenshots = vi.fn()

vi.mock('../../hooks/useBatchStream', () => ({
  useBatchStream: (...args: unknown[]) => useBatchStream(...args),
}))

vi.mock('../../api/screenshots', () => ({
  listScreenshots: (...args: unknown[]) => listScreenshots(...args),
  screenshotPath: (batchId: string, sampleId: string, name: string) =>
    `/api/v1/batches/${batchId}/samples/${sampleId}/screenshots/${name}`,
}))

describe('SampleDetail', () => {
  it('shows screenshot links for the selected sample', async () => {
    useBatchStream.mockReturnValue({
      data: {
        batch_id: 'b1',
        name: 'Batch 1',
        mode: 'gui_pc_web',
        status: 'done',
        total: 1,
        done: 1,
        failed: 0,
        concurrency: 1,
        seq: 2,
        samples: [
          {
            id: 's1',
            prompts: ['hello'],
            mode: 'gui_pc_web',
            target_profile: 'web_demo',
            status: 'done',
            responses: ['world'],
          },
        ],
      },
      isLoading: false,
    })
    listScreenshots.mockResolvedValue([
      { name: '001_ready.png', label: 'ready', taken_at: '2026-04-22T00:00:00Z' },
    ])

    renderWithProviders(
      <Routes>
        <Route path="/batches/:id/samples/:sid" element={<SampleDetail />} />
      </Routes>,
      { initialPath: '/batches/b1/samples/s1' },
    )

    await waitFor(() => {
      expect(screen.getByText('截图')).toBeInTheDocument()
    })
    await waitFor(() => {
      expect(listScreenshots).toHaveBeenCalledWith('b1', 's1')
      expect(screen.getByRole('img', { name: 'ready' })).toHaveAttribute(
        'src',
        '/api/v1/batches/b1/samples/s1/screenshots/001_ready.png',
      )
    })
  })
})
