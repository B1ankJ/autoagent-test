import { screen } from '@testing-library/react'
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

beforeEach(() => {
  mockUseSessionConversation.mockReturnValue({ data: undefined, isLoading: false })
})

it('renders nothing when closed', () => {
  renderWithProviders(
    <SessionConversationModal sessionId={null} onClose={vi.fn()} />,
  )
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
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
