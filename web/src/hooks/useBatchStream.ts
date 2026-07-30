import { useEffect, useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { BatchDetail, SampleUpdate } from '../types/api'

type SseEvent = {
  seq: number
  kind: 'sample_update' | 'batch_progress' | 'batch_done'
  payload: Record<string, unknown>
  ts: string
}

const RECONNECT_DELAY_MS = 1500

export function useBatchStream(id: string | undefined) {
  const queryClient = useQueryClient()
  const seqRef = useRef(0)

  const query = useQuery({
    queryKey: ['batch', id],
    queryFn: async () => {
      const token = localStorage.getItem('autoagent_token') ?? ''
      const response = await fetch(`/api/v1/batches/${id}`, {
        headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' },
      })
      if (!response.ok) {
        throw new Error(`failed to load batch ${id}`)
      }
      const data = (await response.json()) as BatchDetail
      seqRef.current = data.seq ?? 0
      return data
    },
    enabled: !!id,
  })

  useEffect(() => {
    // Gate on isSuccess, not data: every SSE event calls setQueryData,
    // which produces a new `data` reference. Depending on `data` here would
    // re-run this effect (abort + reconnect) on every single event —
    // isSuccess flips false→true once on initial load and then stays put.
    if (!id || !query.isSuccess) return

    const token = localStorage.getItem('autoagent_token') ?? ''
    const abort = new AbortController()
    let stopped = false

    // Opens one /events connection and reads it to completion. Returns
    // 'stop' once a batch_done event lands or the batch is confirmedly gone
    // (404 — no point retrying), 'retry' for anything else (network blip,
    // proxy timeout, server restart) so the caller reconnects instead of
    // silently going stale. after_seq lets the backend replay whatever was
    // published into its buffer during the gap (BatchEventBus.replay_since)
    // — seqRef's own seq<=current guard below still de-dupes if a replayed
    // event also arrives live.
    const connectOnce = async (): Promise<'retry' | 'stop'> => {
      let response: Response
      try {
        response = await fetch(`/api/v1/batches/${id}/events?after_seq=${seqRef.current}`, {
          headers: { Authorization: `Bearer ${token}`, Accept: 'text/event-stream' },
          signal: abort.signal,
        })
      } catch {
        return 'retry'
      }
      if (abort.signal.aborted) return 'stop'
      if (response.status === 404) return 'stop'
      if (!response.ok || !response.body) return 'retry'

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let sawBatchDone = false

      try {
        let active = true
        while (active) {
          const { value, done } = await reader.read()
          if (done) {
            active = false
            continue
          }
          buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
          const chunks = buffer.split('\n\n')
          buffer = chunks.pop() ?? ''

          for (const chunk of chunks) {
            for (const line of chunk.split('\n')) {
              if (!line.startsWith('data: ')) continue
              const event = JSON.parse(line.slice(6)) as SseEvent
              if (event.seq <= seqRef.current) continue
              seqRef.current = event.seq
              queryClient.setQueryData<BatchDetail | undefined>(['batch', id], (prev) =>
                applyEvent(prev, event),
              )
              if (event.kind === 'batch_done') sawBatchDone = true
            }
          }
          if (sawBatchDone) break
        }
      } catch {
        // Connection dropped mid-read — fall through and let the caller retry.
      }
      if (sawBatchDone) reader.cancel().catch(() => {})
      return sawBatchDone ? 'stop' : 'retry'
    }

    const run = async () => {
      while (!stopped && !abort.signal.aborted) {
        const outcome = await connectOnce()
        if (outcome === 'stop' || stopped || abort.signal.aborted) break
        await new Promise((resolve) => setTimeout(resolve, RECONNECT_DELAY_MS))
      }
    }

    run().catch(() => {})
    return () => {
      stopped = true
      abort.abort()
    }
  }, [id, query.isSuccess, queryClient])

  return query
}

export function applyEvent(
  prev: BatchDetail | undefined,
  event: SseEvent,
): BatchDetail | undefined {
  if (!prev) return prev

  const next: BatchDetail = { ...prev, seq: event.seq }
  if (event.kind === 'sample_update') {
    const payload = event.payload as unknown as SampleUpdate
    next.samples = next.samples.map((sample) =>
      sample.id === payload.sample_id
        ? {
            ...sample,
            status: payload.status ?? sample.status,
            device_serial: payload.device_serial ?? sample.device_serial,
            waiting_for_device: payload.waiting_for_device ?? sample.waiting_for_device,
          }
        : sample,
    )
  }
  if (event.kind === 'batch_progress') {
    const payload = event.payload as { done?: number; failed?: number }
    if (typeof payload.done === 'number') next.done = payload.done
    if (typeof payload.failed === 'number') next.failed = payload.failed
  }
  if (event.kind === 'batch_done') {
    const payload = event.payload as { status?: BatchDetail['status'] }
    if (payload.status) next.status = payload.status
  }
  return next
}
