import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { renderWithProviders } from '../test/test-utils'
import { BatchPromptModal } from './BatchPromptModal'

const useBatch = vi.fn()

vi.mock('../api/batches', () => ({
  useBatch: (...args: unknown[]) => useBatch(...args),
}))

describe('BatchPromptModal', () => {
  it('shows the LLM-reviewed response (not just the raw one) when extraction succeeded', async () => {
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
    // Both rule and LLM responses stay visible for comparison...
    expect(screen.getByText('raw extraction')).toBeInTheDocument()
    // ...but only the LLM one is tagged as what was actually returned.
    const llmCard = screen.getByText('LLM 复核（llm_responses）').closest('.ant-card')
    expect(llmCard).not.toBeNull()
    expect(llmCard?.textContent).toContain('实际返回')
    const ruleCard = screen.getByText('主响应（responses）').closest('.ant-card')
    expect(ruleCard?.textContent).not.toContain('实际返回')
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
    const ruleCard = screen.getByText('主响应（responses）').closest('.ant-card')
    expect(ruleCard?.textContent).toContain('实际返回')
  })
})
