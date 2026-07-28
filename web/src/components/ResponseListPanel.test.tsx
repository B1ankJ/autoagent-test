import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../test/test-utils'
import { ResponseListPanel } from './ResponseListPanel'

const entries = [
  {
    target_profile: 'p1',
    response: 'canned reply',
    response_excerpt: 'canned reply',
    added_at: '2026-07-28T00:00:00Z',
  },
]

function renderPanel(overrides: Partial<Parameters<typeof ResponseListPanel>[0]> = {}) {
  const onAdd = vi.fn(async () => {})
  const onRemove = vi.fn(async () => {})
  renderWithProviders(
    <ResponseListPanel
      entries={entries}
      addPending={false}
      removePending={false}
      onAdd={onAdd}
      onRemove={onRemove}
      emptyText="没有记录"
      addButtonLabel="新增记录"
      addModalTitle="新增一条记录"
      {...overrides}
    />,
  )
  return { onAdd, onRemove }
}

describe('ResponseListPanel', () => {
  it('renders entries and lets the user remove one', async () => {
    const { onRemove } = renderPanel()
    expect(screen.getByText('canned reply')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /删\s?除/ }))
    expect(onRemove).toHaveBeenCalledWith({ target_profile: 'p1', response: 'canned reply' })
  })

  it('shows the empty state text when there are no entries', () => {
    renderPanel({ entries: [] })
    expect(screen.getByText('没有记录')).toBeInTheDocument()
  })

  it('opens the add modal and submits a new entry', async () => {
    const { onAdd } = renderPanel()

    await userEvent.click(screen.getByRole('button', { name: /新增记录/ }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText('Profile'), 'p2')
    await userEvent.type(
      within(dialog).getByLabelText('响应内容(需完全匹配)'),
      'new response text',
    )
    await userEvent.click(within(dialog).getByRole('button', { name: /新\s?增/ }))

    await waitFor(() => {
      expect(onAdd).toHaveBeenCalledWith({ target_profile: 'p2', response: 'new response text' })
    })
  })

  it('does not submit when required fields are missing', async () => {
    const { onAdd } = renderPanel()

    await userEvent.click(screen.getByRole('button', { name: /新增记录/ }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: /新\s?增/ }))

    expect(onAdd).not.toHaveBeenCalled()
  })
})
