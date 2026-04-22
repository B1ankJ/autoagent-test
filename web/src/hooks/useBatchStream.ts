import { useEffect, useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { BatchDetail } from '../types/api'

type SseEvent = {
  seq: number
  kind: 'sample_update' | 'batch_progress' | 'batch_done'
  payload: Record<string, unknown>
  ts: string
}

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
    if (!id || !query.data) return

    const token = localStorage.getItem('autoagent_token') ?? ''
    const abort = new AbortController()

    const run = async () => {
      const response = await fetch(`/api/v1/batches/${id}/events`, {
        headers: { Authorization: `Bearer ${token}`, Accept: 'text/event-stream' },
        signal: abort.signal,
      })
      if (!response.ok || !response.body) return

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

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
            if (event.kind === 'batch_done') {
              abort.abort()
            }
          }
        }
      }
    }

    run().catch(() => {})
    return () => abort.abort()
  }, [id, query.data, queryClient])

  return query
}

function applyEvent(prev: BatchDetail | undefined, event: SseEvent): BatchDetail | undefined {
  if (!prev) return prev

  const next: BatchDetail = { ...prev, seq: event.seq }
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
