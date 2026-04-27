import { describe, expect, it, vi } from 'vitest'

import { client } from './client'
import { runSyncRequest } from './tests'

describe('tests api', () => {
  it('passes through a custom timeout for sync runs', async () => {
    const spy = vi.spyOn(client, 'post').mockResolvedValueOnce({ data: { status: 'done' } } as never)

    await runSyncRequest(
      {
        id: 's1',
        prompts: ['hello'],
        mode: 'gui_android',
        target_profile: 'qwen_android',
      },
      210_000,
    )

    expect(spy).toHaveBeenCalledWith('/tests/sync', expect.any(Object), {
      timeout: 210_000,
    })
  })
})
