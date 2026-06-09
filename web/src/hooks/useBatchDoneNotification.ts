import { useEffect, useRef } from 'react'
import type { BatchStatus } from '../types/api'

const TERMINAL: BatchStatus[] = ['done', 'failed', 'cancelled']

interface NotifyArgs {
  batchId: string | undefined
  name: string | undefined
  status: BatchStatus | undefined
  done: number
  failed: number
}

/**
 * Fires a browser notification once when a batch transitions into a terminal
 * state and the tab is not currently focused. No-op when permission isn't
 * granted; opt-in lives with the Notification API itself, not with us.
 */
export function useBatchDoneNotification({ batchId, name, status, done, failed }: NotifyArgs) {
  const lastStatusRef = useRef<BatchStatus | undefined>(undefined)
  const firedRef = useRef<string | null>(null)

  useEffect(() => {
    const prev = lastStatusRef.current
    lastStatusRef.current = status

    if (!batchId || !status) return
    if (!TERMINAL.includes(status)) return
    if (prev !== undefined && TERMINAL.includes(prev)) return // already terminal on previous render
    if (firedRef.current === batchId) return
    if (typeof Notification === 'undefined') return
    if (Notification.permission !== 'granted') return
    // Only notify when the tab is hidden — focused users don't need a popup.
    if (typeof document !== 'undefined' && !document.hidden) return

    firedRef.current = batchId
    try {
      const note = new Notification(`批次 ${name ?? batchId} 已完成`, {
        body: `${status} · done ${done} · failed ${failed}`,
        tag: `aa-batch-${batchId}`,
      })
      note.onclick = () => {
        window.focus()
        window.location.href = `/batches/${batchId}`
        note.close()
      }
    } catch {
      /* Some browsers reject notifications without explicit user gesture; swallow. */
    }
  }, [batchId, name, status, done, failed])
}

export type NotificationPermissionState = 'default' | 'granted' | 'denied' | 'unsupported'

export function getNotificationPermission(): NotificationPermissionState {
  if (typeof Notification === 'undefined') return 'unsupported'
  return Notification.permission as NotificationPermissionState
}

export async function requestNotificationPermission(): Promise<NotificationPermissionState> {
  if (typeof Notification === 'undefined') return 'unsupported'
  if (Notification.permission !== 'default') {
    return Notification.permission as NotificationPermissionState
  }
  const result = await Notification.requestPermission()
  return result as NotificationPermissionState
}
