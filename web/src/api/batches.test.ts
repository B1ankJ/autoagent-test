import { afterEach, describe, expect, it, vi } from 'vitest'
import { downloadSampleLogs } from './batches'
import { client } from './client'

const { triggerDownload } = vi.hoisted(() => ({ triggerDownload: vi.fn() }))

vi.mock('../utils/download', async () => {
  const actual = await vi.importActual<typeof import('../utils/download')>('../utils/download')
  return { ...actual, triggerDownload }
})

describe('downloadSampleLogs', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    triggerDownload.mockClear()
  })

  it('fetches the zip through the authenticated client (not window.open) and triggers a blob download', async () => {
    const blob = new Blob(['zip bytes'])
    const getSpy = vi.spyOn(client, 'get').mockResolvedValue({
      data: blob,
      headers: { 'content-disposition': 'attachment; filename="s1.zip"' },
    } as never)

    await downloadSampleLogs('b1', 's1')

    expect(getSpy).toHaveBeenCalledWith('/batches/b1/samples/s1/logs.zip', {
      responseType: 'blob',
    })
    expect(triggerDownload).toHaveBeenCalledWith(blob, 's1.zip')
  })

  it('falls back to <sampleId>.zip when Content-Disposition is missing', async () => {
    const blob = new Blob(['zip bytes'])
    vi.spyOn(client, 'get').mockResolvedValue({ data: blob, headers: {} } as never)

    await downloadSampleLogs('b1', 's2')

    expect(triggerDownload).toHaveBeenCalledWith(blob, 's2.zip')
  })

  it('propagates a rejection (e.g. missing bearer token) to the caller', async () => {
    vi.spyOn(client, 'get').mockRejectedValue(new Error('Missing bearer token'))

    await expect(downloadSampleLogs('b1', 's1')).rejects.toThrow('Missing bearer token')
  })
})
