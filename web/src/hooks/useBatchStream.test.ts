import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { createElement, ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { applyEvent, useBatchStream } from './useBatchStream'

let fetchCalls: string[] = []
let readerFrames: string[] = []

function encodeStream(frames: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    async start(controller) {
      for (const frame of frames) {
        controller.enqueue(encoder.encode(frame))
        await new Promise((resolve) => setTimeout(resolve, 10))
      }
      controller.close()
    },
  })
}

beforeEach(() => {
  fetchCalls = []
  localStorage.setItem('autoagent_token', 'tok')
  global.fetch = vi.fn(async (url: string) => {
    fetchCalls.push(String(url))
    if (String(url).includes('/events')) {
      return new Response(encodeStream(readerFrames), {
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
      })
    }
    return new Response(
      JSON.stringify({
        batch_id: 'b1',
        name: 'n',
        mode: 'api',
        status: 'running',
        total: 3,
        done: 0,
        failed: 0,
        seq: 0,
        concurrency: 1,
        samples: [],
      }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    )
  }) as typeof fetch
})

afterEach(() => {
  vi.restoreAllMocks()
})

function withProvider(children: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return createElement(QueryClientProvider, { client: queryClient }, children)
}

describe('useBatchStream', () => {
  it('applies batch_progress events to cached data', async () => {
    readerFrames = [
      'data: {"seq":1,"kind":"batch_progress","payload":{"done":1,"failed":0,"total":3},"ts":"t"}\n\n',
      'data: {"seq":2,"kind":"batch_done","payload":{"status":"done"},"ts":"t"}\n\n',
    ]
    const { result } = renderHook(() => useBatchStream('b1'), {
      wrapper: ({ children }) => withProvider(children),
    })
    await waitFor(() => expect(result.current.data?.done).toBe(1))
    await waitFor(() => expect(result.current.data?.status).toBe('done'))
  })

  it('drops events with seq <= initial', async () => {
    readerFrames = [
      'data: {"seq":0,"kind":"batch_progress","payload":{"done":99},"ts":"t"}\n\n',
      'data: {"seq":1,"kind":"batch_progress","payload":{"done":5},"ts":"t"}\n\n',
      'data: {"seq":2,"kind":"batch_done","payload":{"status":"done"},"ts":"t"}\n\n',
    ]
    const { result } = renderHook(() => useBatchStream('b1'), {
      wrapper: ({ children }) => withProvider(children),
    })
    await waitFor(() => expect(result.current.data?.done).toBe(5))
    expect(result.current.data?.done).not.toBe(99)
  })

  it('keeps a single SSE connection open across multiple events', async () => {
    // Regression test: the effect used to depend on `query.data`, which
    // every event mutates via setQueryData — reopening /events on each
    // event instead of reusing one connection.
    readerFrames = [
      'data: {"seq":1,"kind":"batch_progress","payload":{"done":1,"failed":0,"total":3},"ts":"t"}\n\n',
      'data: {"seq":2,"kind":"batch_progress","payload":{"done":2,"failed":0,"total":3},"ts":"t"}\n\n',
      'data: {"seq":3,"kind":"batch_done","payload":{"status":"done"},"ts":"t"}\n\n',
    ]
    const { result } = renderHook(() => useBatchStream('b1'), {
      wrapper: ({ children }) => withProvider(children),
    })
    await waitFor(() => expect(result.current.data?.status).toBe('done'))

    const eventsCalls = fetchCalls.filter((url) => url.includes('/events'))
    expect(eventsCalls).toHaveLength(1)
  })

  it('reconnects with after_seq when the stream drops without batch_done', async () => {
    let eventsCall = 0
    global.fetch = vi.fn(async (url: string) => {
      fetchCalls.push(String(url))
      if (String(url).includes('/events')) {
        eventsCall += 1
        if (eventsCall === 1) {
          // Connection drops mid-batch (network blip / server restart) —
          // the stream just ends, no batch_done event.
          return new Response(
            encodeStream([
              'data: {"seq":1,"kind":"batch_progress","payload":{"done":1,"failed":0,"total":3},"ts":"t"}\n\n',
            ]),
            { status: 200, headers: { 'content-type': 'text/event-stream' } },
          )
        }
        // Reconnect: the backend replays whatever the buffer still has
        // after seq 1, then the batch finishes normally.
        return new Response(
          encodeStream([
            'data: {"seq":2,"kind":"batch_progress","payload":{"done":2,"failed":0,"total":3},"ts":"t"}\n\n',
            'data: {"seq":3,"kind":"batch_done","payload":{"status":"done"},"ts":"t"}\n\n',
          ]),
          { status: 200, headers: { 'content-type': 'text/event-stream' } },
        )
      }
      return new Response(
        JSON.stringify({
          batch_id: 'b1',
          name: 'n',
          mode: 'api',
          status: 'running',
          total: 3,
          done: 0,
          failed: 0,
          seq: 0,
          concurrency: 1,
          samples: [],
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      )
    }) as typeof fetch

    const { result } = renderHook(() => useBatchStream('b1'), {
      wrapper: ({ children }) => withProvider(children),
    })
    await waitFor(() => expect(result.current.data?.status).toBe('done'), { timeout: 5000 })
    expect(result.current.data?.done).toBe(2)

    const eventsCalls = fetchCalls.filter((url) => url.includes('/events'))
    expect(eventsCalls).toHaveLength(2)
    // The reconnect passes the last seq it actually saw so the backend can
    // replay the gap instead of the client silently missing it forever.
    expect(eventsCalls[1]).toContain('after_seq=1')
  })

  it('applies sample_update device fields', () => {
    const next = applyEvent(
      {
        batch_id: 'b1',
        name: 'n',
        mode: 'gui_android',
        status: 'running',
        total: 1,
        done: 0,
        failed: 0,
        concurrency: 1,
        samples: [{ id: 's1', status: 'running' }],
        seq: 1,
      } as never,
      {
        seq: 2,
        kind: 'sample_update',
        payload: {
          sample_id: 's1',
          status: 'running',
          device_serial: 'emulator-5554',
          waiting_for_device: false,
        },
        ts: '2026-04-22T00:00:00Z',
      },
    )

    expect(next?.samples[0].device_serial).toBe('emulator-5554')
    expect(next?.samples[0].waiting_for_device).toBe(false)
  })
})
