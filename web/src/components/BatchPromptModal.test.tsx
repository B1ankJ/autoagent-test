import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { renderWithProviders } from '../test/test-utils'
import { BatchPromptModal } from './BatchPromptModal'

const useBatch = vi.fn()

vi.mock('../api/batches', () => ({
  useBatch: (...args: unknown[]) => useBatch(...args),
}))

describe('BatchPromptModal', () => {
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
})
