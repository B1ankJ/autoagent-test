import { screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Route, Routes } from 'react-router-dom'
import { client } from '../../api/client'
import { renderWithProviders } from '../../test/test-utils'
import { BatchDetail } from './Detail'

describe('BatchDetail', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders batch info', async () => {
    vi.spyOn(client, 'get').mockResolvedValue({
      data: {
        batch_id: 'b1',
        name: 'Test',
        mode: 'api',
        status: 'done',
        total: 3,
        done: 3,
        failed: 0,
        concurrency: 1,
        samples: [],
      },
    } as never)

    renderWithProviders(
      <Routes>
        <Route path="/batches/:id" element={<BatchDetail />} />
      </Routes>,
      { initialPath: '/batches/b1' },
    )

    await waitFor(() => {
      expect(screen.getByText('Test')).toBeInTheDocument()
    })
    expect(screen.getByText('done')).toBeInTheDocument()
    expect(screen.getByText(/3 \/ 3 完成/)).toBeInTheDocument()
  })
})
