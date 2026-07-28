import type { HTMLAttributes, MouseEvent as ReactMouseEvent, ReactNode } from 'react'

interface ResizableHeaderCellProps extends HTMLAttributes<HTMLElement> {
  width?: number
  onResizeStart?: (e: ReactMouseEvent) => void
  children?: ReactNode
}

/** Custom header <th> that adds a drag handle on its right edge — passed
 * to Table's `components.header.cell`. Columns without a resize handler
 * (i.e. those useResizableColumns left alone) render as a plain <th>. */
export function ResizableHeaderCell({
  width,
  onResizeStart,
  children,
  ...restProps
}: ResizableHeaderCellProps) {
  if (width === undefined || !onResizeStart) {
    return <th {...restProps}>{children}</th>
  }
  return (
    <th {...restProps} style={{ ...restProps.style, position: 'relative' }}>
      {children}
      <span
        onMouseDown={onResizeStart}
        onClick={(e) => e.stopPropagation()}
        style={{
          position: 'absolute',
          right: -4,
          top: 0,
          bottom: 0,
          width: 8,
          cursor: 'col-resize',
          userSelect: 'none',
          zIndex: 1,
        }}
      />
    </th>
  )
}
