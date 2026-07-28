import type { ColumnsType } from 'antd/es/table'
import type { MouseEvent as ReactMouseEvent } from 'react'
import { useCallback, useRef, useState } from 'react'

import { ResizableHeaderCell } from './ResizableHeaderCell'

const MIN_COLUMN_WIDTH = 60

function loadWidths(storageKey: string | undefined): Record<string, number> {
  if (!storageKey) return {}
  try {
    const raw = localStorage.getItem(storageKey)
    if (!raw) return {}
    const parsed: unknown = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return {}
    return parsed as Record<string, number>
  } catch {
    return {}
  }
}

/**
 * Adds drag-to-resize handles to every column that already has an explicit
 * numeric `width` (columns left auto/flex-width, e.g. a "name" column
 * meant to fill remaining space, are left untouched). Widths persist to
 * localStorage per `storageKey` so the layout survives a reload.
 *
 * Usage: `const { columns, components } = useResizableColumns(rawColumns, 'my_table_key')`
 * then pass both straight through to `<Table columns={columns} components={components} />`.
 */
export function useResizableColumns<T>(
  columns: ColumnsType<T>,
  storageKey?: string,
): { columns: ColumnsType<T>; components: Record<string, unknown> } {
  const [widths, setWidths] = useState<Record<string, number>>(() => loadWidths(storageKey))
  const widthsRef = useRef(widths)
  widthsRef.current = widths

  const startResize = useCallback(
    (key: string, startWidth: number) => (e: ReactMouseEvent) => {
      e.preventDefault()
      e.stopPropagation()
      const startX = e.clientX

      const onMove = (ev: globalThis.MouseEvent) => {
        const next = Math.max(MIN_COLUMN_WIDTH, startWidth + (ev.clientX - startX))
        setWidths((prev) => ({ ...prev, [key]: next }))
      }
      const onUp = () => {
        window.removeEventListener('mousemove', onMove)
        window.removeEventListener('mouseup', onUp)
        if (storageKey) {
          try {
            localStorage.setItem(storageKey, JSON.stringify(widthsRef.current))
          } catch {
            /* private mode etc; persistence is best-effort */
          }
        }
      }
      window.addEventListener('mousemove', onMove)
      window.addEventListener('mouseup', onUp)
    },
    [storageKey],
  )

  const resized = columns.map((col) => {
    const dataIndex = 'dataIndex' in col ? col.dataIndex : undefined
    const key = String(col.key ?? dataIndex ?? '')
    const baseWidth = typeof col.width === 'number' ? col.width : undefined
    if (!key || baseWidth === undefined) return col
    const width = widths[key] ?? baseWidth
    return {
      ...col,
      width,
      onHeaderCell: () => ({
        width,
        onResizeStart: startResize(key, width),
      }),
    }
  })

  return {
    columns: resized,
    components: { header: { cell: ResizableHeaderCell } },
  }
}
