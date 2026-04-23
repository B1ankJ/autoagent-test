import { describe, expect, it, vi, afterEach } from 'vitest'

import { client } from './client'
import {
  fetchProfileBuilderArtifactBlobUrl,
  fetchProfileBuilderRuntime,
} from './profileBuilderRuntime'

describe('profileBuilderRuntime api', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('fetches runtime by session id', async () => {
    vi.spyOn(client, 'get').mockResolvedValueOnce({
      data: { session_id: 'pb_1', current_step: 'capture_idle' },
    } as never)

    const data = await fetchProfileBuilderRuntime('pb_1')

    expect(client.get).toHaveBeenCalledWith('/profile-builder/sessions/pb_1/runtime')
    expect(data.session_id).toBe('pb_1')
  })

  it('fetches artifact as blob url', async () => {
    const blob = new Blob(['png'])
    vi.spyOn(client, 'get').mockResolvedValueOnce({ data: blob } as never)
    Object.defineProperty(URL, 'createObjectURL', {
      value: vi.fn(() => 'blob:preview'),
      configurable: true,
    })
    const createObjectURL = vi
      .spyOn(URL, 'createObjectURL')
      .mockReturnValueOnce('blob:preview')

    const url = await fetchProfileBuilderArtifactBlobUrl('pb_1', 'capture_idle.png')

    expect(client.get).toHaveBeenCalledWith(
      '/profile-builder/sessions/pb_1/artifacts/capture_idle.png',
      { responseType: 'blob' },
    )
    expect(createObjectURL).toHaveBeenCalledWith(blob)
    expect(url).toBe('blob:preview')
  })
})
