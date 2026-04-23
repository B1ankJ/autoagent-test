import { describe, expect, it, vi, afterEach } from 'vitest'

import { client } from './client'
import { fetchProfileBuilderRuntime } from './profileBuilderRuntime'

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
})
