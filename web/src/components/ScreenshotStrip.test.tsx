import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { renderWithProviders } from '../test/test-utils'
import { ScreenshotStrip } from './ScreenshotStrip'

const listScreenshots = vi.fn()

vi.mock('../api/screenshots', () => ({
  listScreenshots: (...args: unknown[]) => listScreenshots(...args),
  screenshotPath: (batchId: string, sampleId: string, name: string) =>
    `/api/v1/batches/${batchId}/samples/${sampleId}/screenshots/${name}`,
}))

describe('ScreenshotStrip', () => {
  it('renders screenshot previews for a sample', async () => {
    listScreenshots.mockResolvedValue([
      { name: '001_ready.png', label: 'ready', taken_at: '2026-04-22T00:00:00Z' },
    ])

    renderWithProviders(<ScreenshotStrip batchId="b1" sampleId="s1" />)

    await waitFor(() => {
      expect(listScreenshots).toHaveBeenCalledWith('b1', 's1')
      expect(screen.getByRole('img', { name: 'ready' })).toHaveAttribute(
        'src',
        '/api/v1/batches/b1/samples/s1/screenshots/001_ready.png',
      )
    })
  })
})
