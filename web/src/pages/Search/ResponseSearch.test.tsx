import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Route, Routes, useLocation } from 'react-router-dom'
import { renderWithProviders } from '../../test/test-utils'
import type { SampleSearchHit } from '../../types/api'
import { ResponseSearch } from './ResponseSearch'

const useSampleSearch = vi.fn()

vi.mock('../../api/search', () => ({
  useSampleSearch: (...a: unknown[]) => useSampleSearch(...a),
}))
vi.mock('../../api/profiles', () => ({ useProfiles: () => ({ data: [] }) }))

function hit(over: Partial<SampleSearchHit> & { sample_id: string }): SampleSearchHit {
  return {
    batch_id: 'b1',
    target_profile: 'p1',
    status: 'done',
    ended_at: '2026-08-05T00:00:00Z',
    source: 'response',
    snippet: '…前面 抱歉我无法 后面…',
    ...over,
  }
}

function SampleStub() {
  const loc = useLocation()
  return <div>sample-page{loc.pathname}</div>
}

describe('ResponseSearch', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  it('renders hits with a snippet and links to the sample', async () => {
    useSampleSearch.mockReturnValue({
      data: { items: [hit({ sample_id: 's1', batch_id: 'bb' })], total: 1 },
      isLoading: false,
      isError: false,
    })
    renderWithProviders(
      <Routes>
        <Route path="/search/responses" element={<ResponseSearch />} />
        <Route path="/batches/:id/samples/:sid" element={<SampleStub />} />
      </Routes>,
      { initialPath: '/search/responses' },
    )
    await userEvent.type(screen.getByPlaceholderText(/搜索响应/), '抱歉我无法')
    await userEvent.keyboard('{Enter}')
    // the source tag and 共 N 条 render once results are shown
    await waitFor(() => expect(screen.getByText('原始响应')).toBeInTheDocument())
    expect(screen.getByText(/共 1 条命中/)).toBeInTheDocument()
    await userEvent.click(screen.getByText('查看'))
    expect(await screen.findByText('sample-page/batches/bb/samples/s1')).toBeInTheDocument()
  })

  it('restores the query from the URL (survives navigating away and back)', async () => {
    useSampleSearch.mockReturnValue({
      data: { items: [hit({ sample_id: 's1' })], total: 1 },
      isLoading: false,
      isError: false,
    })
    renderWithProviders(
      <Routes>
        <Route path="/search/responses" element={<ResponseSearch />} />
      </Routes>,
      // as if the browser restored the URL that carried the search
      { initialPath: '/search/responses?q=抱歉我无法' },
    )
    // results show immediately without re-typing, and the box is prefilled
    await waitFor(() => expect(screen.getByText('原始响应')).toBeInTheDocument())
    expect(screen.getByDisplayValue('抱歉我无法')).toBeInTheDocument()
    // the hook was driven by the URL's q
    const lastArgs = useSampleSearch.mock.calls.at(-1)?.[0] as { q: string } | undefined
    expect(lastArgs?.q).toBe('抱歉我无法')
  })

  it('renders the Prompt source tag and restores scope/status from the URL', async () => {
    useSampleSearch.mockReturnValue({
      data: { items: [hit({ sample_id: 's1', source: 'prompt' })], total: 1 },
      isLoading: false,
      isError: false,
    })
    renderWithProviders(
      <Routes>
        <Route path="/search/responses" element={<ResponseSearch />} />
      </Routes>,
      { initialPath: '/search/responses?q=abc&fields=prompt&status=failed' },
    )
    await waitFor(() => expect(screen.getByText('Prompt')).toBeInTheDocument())
    const args = useSampleSearch.mock.calls.at(-1)?.[0] as
      | { fields?: string; status?: string[] }
      | undefined
    expect(args?.fields).toBe('prompt')
    expect(args?.status).toEqual(['failed'])
  })
})
