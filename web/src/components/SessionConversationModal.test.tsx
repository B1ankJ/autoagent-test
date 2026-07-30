import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'

import { renderWithProviders } from '../test/test-utils'
import type { SessionTurn } from '../types/api'
import { SessionConversationModal } from './SessionConversationModal'

const { mockUseSessionConversation } = vi.hoisted(() => ({
  mockUseSessionConversation: vi.fn(),
}))

vi.mock('../api/batches', () => ({
  useSessionConversation: mockUseSessionConversation,
}))

const { listScreenshots } = vi.hoisted(() => ({ listScreenshots: vi.fn() }))

vi.mock('../api/screenshots', () => ({
  listScreenshots: (...args: unknown[]) => listScreenshots(...args),
  screenshotUrl: (batchId: string, sampleId: string, name: string, width?: number) =>
    `/api/v1/media/batches/${batchId}/samples/${sampleId}/screenshot/${name}${
      width ? `?w=${width}` : ''
    }`,
}))

beforeEach(() => {
  mockUseSessionConversation.mockReturnValue({ data: undefined, isLoading: false })
  listScreenshots.mockResolvedValue([])
})

it('renders nothing when closed', () => {
  renderWithProviders(
    <SessionConversationModal sessionId={null} onClose={vi.fn()} />,
  )
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

it('shows an error alert (not the empty state) when the query fails', async () => {
  // Regression: isError was never checked — a failed fetch rendered the
  // exact same "没有找到属于这个会话的记录" empty state as a genuinely
  // empty session, misleading users about a real fetch error.
  const refetch = vi.fn()
  mockUseSessionConversation.mockReturnValue({
    data: undefined,
    isLoading: false,
    isError: true,
    error: new Error('network down'),
    refetch,
  })
  renderWithProviders(<SessionConversationModal sessionId="conv-1" onClose={vi.fn()} />)

  expect(screen.getByText('加载失败')).toBeInTheDocument()
  expect(screen.getByText('network down')).toBeInTheDocument()
  expect(screen.queryByText('没有找到属于这个会话的记录')).not.toBeInTheDocument()

  await userEvent.click(screen.getByRole('button', { name: /重\s?试/ }))
  expect(refetch).toHaveBeenCalled()
})

it('shows an empty state when the session has no turns', () => {
  mockUseSessionConversation.mockReturnValue({ data: [], isLoading: false })
  renderWithProviders(
    <SessionConversationModal sessionId="conv-1" onClose={vi.fn()} />,
  )
  expect(screen.getByText('没有找到属于这个会话的记录')).toBeInTheDocument()
})

it('renders turns in order with prompt, response, and status', () => {
  const turns: SessionTurn[] = [
    {
      batch_id: 'b1',
      sample_id: 's1',
      status: 'done',
      prompt: 'hi',
      response: 'hello!',
      started_at: '2026-01-01T00:00:00Z',
    },
    {
      batch_id: 'b2',
      sample_id: 's2',
      status: 'done',
      prompt: 'how are you',
      response: 'good, thanks',
      started_at: '2026-01-01T00:01:00Z',
    },
  ]
  mockUseSessionConversation.mockReturnValue({ data: turns, isLoading: false })
  renderWithProviders(
    <SessionConversationModal sessionId="conv-1" onClose={vi.fn()} />,
  )

  expect(screen.getByText('第 1 轮')).toBeInTheDocument()
  expect(screen.getByText('第 2 轮')).toBeInTheDocument()
  expect(screen.getByText('hi')).toBeInTheDocument()
  expect(screen.getByText('hello!')).toBeInTheDocument()
  expect(screen.getByText('how are you')).toBeInTheDocument()
  expect(screen.getByText('good, thanks')).toBeInTheDocument()
})

it('fetches each turn\'s screenshots and bolds the Prompt/Response labels', async () => {
  const turns: SessionTurn[] = [
    {
      batch_id: 'b1',
      sample_id: 's1',
      status: 'done',
      prompt: 'hi',
      response: 'hello!',
      started_at: '2026-01-01T00:00:00Z',
    },
  ]
  mockUseSessionConversation.mockReturnValue({ data: turns, isLoading: false })
  renderWithProviders(<SessionConversationModal sessionId="conv-1" onClose={vi.fn()} />)

  expect(screen.getByText('PROMPT')).toBeInTheDocument()
  expect(screen.getByText('RESPONSE')).toBeInTheDocument()
  await waitFor(() => {
    expect(listScreenshots).toHaveBeenCalledWith('b1', 's1')
  })
})

it('shows a no-op note for a turn that never ran (e.g. end_session)', () => {
  const turns: SessionTurn[] = [
    { batch_id: 'b1', sample_id: 's1', status: 'done', prompt: null, response: null },
  ]
  mockUseSessionConversation.mockReturnValue({ data: turns, isLoading: false })
  renderWithProviders(
    <SessionConversationModal sessionId="conv-1" onClose={vi.fn()} />,
  )
  expect(screen.getByText('未执行(如释放设备的空操作)')).toBeInTheDocument()
})
