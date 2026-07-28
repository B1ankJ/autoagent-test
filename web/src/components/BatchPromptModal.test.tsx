import { screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { renderWithProviders } from '../test/test-utils'
import { BatchPromptModal } from './BatchPromptModal'

const useBatch = vi.fn()
const listScreenshots = vi.fn()

vi.mock('../api/batches', () => ({
  useBatch: (...args: unknown[]) => useBatch(...args),
}))

vi.mock('../api/screenshots', () => ({
  listScreenshots: (...args: unknown[]) => listScreenshots(...args),
  screenshotUrl: (batchId: string, sampleId: string, name: string, width?: number) =>
    `/api/v1/media/batches/${batchId}/samples/${sampleId}/screenshot/${name}${
      width ? `?w=${width}` : ''
    }`,
}))

describe('BatchPromptModal', () => {
  beforeEach(() => {
    listScreenshots.mockReset()
    listScreenshots.mockResolvedValue([])
  })

  it('shows a single response — the LLM-reviewed one — when extraction succeeded', async () => {
    useBatch.mockReturnValue({
      isLoading: false,
      error: null,
      data: {
        batch_id: 'b1',
        name: 'Batch 1',
        status: 'done',
        samples: [
          {
            id: 's1',
            prompts_sent: ['hi'],
            responses: ['raw extraction'],
            llm_responses: ['llm-reviewed answer'],
            llm_errors: [null],
          },
        ],
      },
    })

    renderWithProviders(<BatchPromptModal batchId="b1" onClose={() => {}} />)

    await waitFor(() => {
      expect(screen.getByText('llm-reviewed answer')).toBeInTheDocument()
    })
    // Only the effective (LLM-reviewed) text shows — no raw/LLM split view.
    expect(screen.queryByText('raw extraction')).not.toBeInTheDocument()
    expect(screen.queryByText('主响应（responses）')).not.toBeInTheDocument()
    expect(screen.queryByText('LLM 复核（llm_responses）')).not.toBeInTheDocument()
    // One-click copy still available, like before.
    expect(document.querySelector('.ant-typography-copy')).not.toBeNull()
  })

  it('falls back to the raw response when LLM extraction is not configured', async () => {
    useBatch.mockReturnValue({
      isLoading: false,
      error: null,
      data: {
        batch_id: 'b2',
        name: 'Batch 2',
        status: 'done',
        samples: [
          {
            id: 's1',
            prompts_sent: ['hi'],
            responses: ['raw extraction'],
          },
        ],
      },
    })

    renderWithProviders(<BatchPromptModal batchId="b2" onClose={() => {}} />)

    await waitFor(() => {
      expect(screen.getByText('raw extraction')).toBeInTheDocument()
    })
  })

  it('falls back to the raw response when LLM extraction failed', async () => {
    useBatch.mockReturnValue({
      isLoading: false,
      error: null,
      data: {
        batch_id: 'b3',
        name: 'Batch 3',
        status: 'done',
        samples: [
          {
            id: 's1',
            prompts_sent: ['hi'],
            responses: ['raw extraction'],
            llm_responses: [''],
            llm_errors: ['auth'],
          },
        ],
      },
    })

    renderWithProviders(<BatchPromptModal batchId="b3" onClose={() => {}} />)

    await waitFor(() => {
      expect(screen.getByText('raw extraction')).toBeInTheDocument()
    })
  })

  it('fetches and shows the sample screenshots alongside prompt/response', async () => {
    listScreenshots.mockResolvedValue([
      { name: 'after_result_1.png', label: 'after_result_1', taken_at: '2026-04-22T00:00:00Z' },
    ])
    useBatch.mockReturnValue({
      isLoading: false,
      error: null,
      data: {
        batch_id: 'b4',
        name: 'Batch 4',
        status: 'done',
        samples: [
          {
            id: 's1',
            prompts_sent: ['hi'],
            responses: ['raw extraction'],
          },
        ],
      },
    })

    renderWithProviders(<BatchPromptModal batchId="b4" onClose={() => {}} />)

    expect(await screen.findByText('截图')).toBeInTheDocument()
    await waitFor(() => {
      expect(listScreenshots).toHaveBeenCalledWith('b4', 's1')
    })
    expect(screen.getByAltText('after_result_1')).toBeInTheDocument()
  })
})
