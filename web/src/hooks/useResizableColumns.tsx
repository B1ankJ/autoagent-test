import type { ColumnsType } from 'antd/es/table'
import type { MouseEvent as ReactMouseEvent } from 'react'
import { useCallback, useRef, useState } from 'react'

import { ResizableHeaderCell } from './ResizableHeaderCell'

const MIN_COLUMN_WIDTH = 60
// Applied to columns left without an explicit `width` (e.g. a "name" column
// meant to fill remaining space) so every column becomes a real, independently
// resizable pixel width — see the tableLayout/scroll note below for why.
const DEFAULT_FLEX_WIDTH = 260

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
 * Adds drag-to-resize handles to every column that has a `key`/`dataIndex`,
 * including ones left without an explicit numeric `width` in the source
 * column config (those get `DEFAULT_FLEX_WIDTH` so every border between two
 * columns is draggable, not just borders next to already-sized columns).
 * Widths persist to localStorage per `storageKey` so the layout survives a
 * reload.
 *
 * Every column ending up with a real pixel width only behaves correctly
 * under `table-layout: fixed` — with the default `auto` layout the browser
 * recomputes column widths from cell content on every render and silently
 * overrides/redistributes the widths we set, which is what made resizing
 * feel like it moved the wrong border in the wrong direction. So this also
 * returns a `scroll.x` (sum of all column widths) — pass both `scroll` and
 * `tableLayout="fixed"` through to `<Table>` alongside `columns`/`components`
 * so growing a column grows the table (and scrolls) instead of squeezing an
 * unconstrained neighbor.
 *
 * Usage:
 * ```
 * const { columns, components, scroll } = useResizableColumns(rawColumns, 'my_table_key')
 * <Table columns={columns} components={components} scroll={scroll} tableLayout="fixed" />
 * ```
 */
export function useResizableColumns<T>(
  columns: ColumnsType<T>,
  storageKey?: string,
): {
  columns: ColumnsType<T>
  components: Record<string, unknown>
  scroll: { x: number }
} {
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
    if (!key) return col
    const baseWidth = typeof col.width === 'number' ? col.width : DEFAULT_FLEX_WIDTH
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

  const totalWidth = resized.reduce(
    (sum, col) => sum + (typeof col.width === 'number' ? col.width : 0),
    0,
  )

  return {
    columns: resized,
    components: { header: { cell: ResizableHeaderCell } },
    scroll: { x: totalWidth },
  }
}
