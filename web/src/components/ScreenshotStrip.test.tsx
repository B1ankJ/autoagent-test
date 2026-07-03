import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { renderWithProviders } from '../test/test-utils'
import { ScreenshotStrip } from './ScreenshotStrip'

const listScreenshots = vi.fn()

vi.mock('../api/screenshots', () => ({
  listScreenshots: (...args: unknown[]) => listScreenshots(...args),
  screenshotUrl: (batchId: string, sampleId: string, name: string, width?: number) =>
    `/api/v1/media/batches/${batchId}/samples/${sampleId}/screenshot/${name}${
      width ? `?w=${width}` : ''
    }`,
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

    renderWithProviders(<ScreenshotStrip batchId="b1" sampleId="s1" />)

    await waitFor(() => {
      expect(listScreenshots).toHaveBeenCalledWith('b1', 's1')
      // Thumbnail img points at the media endpoint with a width param.
      expect(screen.getByRole('img', { name: 'before_input_1' })).toHaveAttribute(
        'src',
        '/api/v1/media/batches/b1/samples/s1/screenshot/before_input_1.png?w=336',
      )
      // Step number rendered as a zero-padded badge overlay (`01`).
      expect(screen.getByText('01')).toBeInTheDocument()
      expect(screen.getByText('输入前 1')).toBeInTheDocument()
      expect(screen.getByText('before_input_1')).toBeInTheDocument()
    })
  })
})
