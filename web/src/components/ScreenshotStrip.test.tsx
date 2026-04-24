import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { renderWithProviders } from '../test/test-utils'
import { ScreenshotStrip } from './ScreenshotStrip'

const listScreenshots = vi.fn()
const fetchScreenshotBlobUrl = vi.fn()

vi.mock('../api/screenshots', () => ({
  listScreenshots: (...args: unknown[]) => listScreenshots(...args),
  fetchScreenshotBlobUrl: (...args: unknown[]) => fetchScreenshotBlobUrl(...args),
}))

describe('ScreenshotStrip', () => {
  it('renders screenshot previews for a sample', async () => {
    listScreenshots.mockResolvedValue([
      {
        name: 'before_input_1.png',
        label: 'before_input_1',
        taken_at: '2026-04-22T00:00:00Z',
      },
    ])
    fetchScreenshotBlobUrl.mockResolvedValue('blob:ready')

    renderWithProviders(<ScreenshotStrip batchId="b1" sampleId="s1" />)

    await waitFor(() => {
      expect(listScreenshots).toHaveBeenCalledWith('b1', 's1')
      expect(fetchScreenshotBlobUrl).toHaveBeenCalledWith('b1', 's1', 'before_input_1.png')
      expect(screen.getByRole('img', { name: 'before_input_1' })).toHaveAttribute(
        'src',
        'blob:ready',
      )
      expect(screen.getByText('输入前 1')).toBeInTheDocument()
    })
  })
})
