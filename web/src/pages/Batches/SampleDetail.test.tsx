import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Route, Routes } from 'react-router-dom'
import { renderWithProviders } from '../../test/test-utils'
import { SampleDetail } from './SampleDetail'

const useBatchStream = vi.fn()
const listScreenshots = vi.fn()
const downloadSampleActions = vi.fn()

vi.mock('../../hooks/useBatchStream', () => ({
  useBatchStream: (...args: unknown[]) => useBatchStream(...args),
}))

vi.mock('../../api/screenshots', () => ({
  listScreenshots: (...args: unknown[]) => listScreenshots(...args),
  screenshotPath: (batchId: string, sampleId: string, name: string) =>
    `/api/v1/batches/${batchId}/samples/${sampleId}/screenshots/${name}`,
}))

vi.mock('../../api/batches', async () => {
  const actual = await vi.importActual('../../api/batches')
  return {
    ...actual,
    downloadSampleActions: (...args: unknown[]) => downloadSampleActions(...args),
  }
})

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
            device_serial: 'emulator-5554',
            responses: ['world'],
            metadata: { action_replay_available: true },
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
    expect(screen.getByText('运行设备')).toBeInTheDocument()
    expect(screen.getByText('emulator-5554')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /下载回放/i })).toBeInTheDocument()
    await waitFor(() => {
      expect(listScreenshots).toHaveBeenCalledWith('b1', 's1')
      expect(screen.getByRole('img', { name: 'ready' })).toHaveAttribute(
        'src',
        '/api/v1/batches/b1/samples/s1/screenshots/001_ready.png',
      )
    })

    await userEvent.click(screen.getByRole('button', { name: /下载回放/i }))
    expect(downloadSampleActions).toHaveBeenCalledWith('b1', 's1')
  })

  it('renders prompt rounds from prompts_sent when prompts is absent', async () => {
    useBatchStream.mockReturnValue({
      data: {
        batch_id: 'b2',
        name: 'Batch 2',
        mode: 'gui_pc_web',
        status: 'done',
        total: 1,
        done: 1,
        failed: 0,
        concurrency: 1,
        seq: 3,
        samples: [
          {
            id: 's2',
            prompts_sent: ['hello'],
            mode: 'gui_pc_web',
            target_profile: 'web_demo',
            status: 'done',
            responses: ['echo: hello'],
          },
        ],
      },
      isLoading: false,
    })
    listScreenshots.mockResolvedValue([])

    renderWithProviders(
      <Routes>
        <Route path="/batches/:id/samples/:sid" element={<SampleDetail />} />
      </Routes>,
      { initialPath: '/batches/b2/samples/s2' },
    )

    await userEvent.click(screen.getByRole('button', { name: /第 1 轮/i }))
    await waitFor(() => {
      expect(screen.getByText('hello')).toBeInTheDocument()
      expect(screen.getByText('echo: hello')).toBeInTheDocument()
    })
  })
})
