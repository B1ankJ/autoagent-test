import { fireEvent, render } from '@testing-library/react'
import { Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { describe, expect, it } from 'vitest'

import { useResizableColumns } from './useResizableColumns'

interface Row {
  key: string
  name: string
}

const RAW_COLUMNS: ColumnsType<Row> = [
  { key: 'name', title: '名称', dataIndex: 'name' }, // no explicit width — left alone
  { key: 'fixed', title: 'Fixed', dataIndex: 'name', width: 150 },
]

const DATA: Row[] = [{ key: '1', name: 'hello' }]

function TestTable({ storageKey }: { storageKey?: string }) {
  const { columns, components, scroll } = useResizableColumns(RAW_COLUMNS, storageKey)
  return (
    <Table<Row>
      rowKey="key"
      columns={columns}
      dataSource={DATA}
      components={components}
      scroll={scroll}
      tableLayout="fixed"
    />
  )
}

describe('useResizableColumns', () => {
  it('adds a resize handle to every column, including ones without an explicit width', () => {
    const { container } = render(<TestTable />)
    const headers = container.querySelectorAll('th')
    // "名称" has no explicit width in RAW_COLUMNS, but every border must be
    // draggable (a border can't be resized if only one of its two columns
    // has a handle), so it still gets one — defaulted to DEFAULT_FLEX_WIDTH.
    expect(headers[0].querySelector('span[style*="cursor: col-resize"]')).not.toBeNull()
    expect(headers[1].querySelector('span[style*="cursor: col-resize"]')).not.toBeNull()
    const cols = container.querySelectorAll('colgroup col')
    expect((cols[0] as HTMLElement).style.width).toBe('260px')
    expect((cols[1] as HTMLElement).style.width).toBe('150px')
  })

  it('grows (not shrinks) a column when dragging its handle rightward', () => {
    const { container } = render(<TestTable />)
    const handle = container.querySelectorAll('th')[0].querySelector('span')!
    fireEvent.mouseDown(handle, { clientX: 100 })
    fireEvent.mouseMove(window, { clientX: 140 })
    fireEvent.mouseUp(window)
    const nameCol = container.querySelectorAll('colgroup col')[0] as HTMLElement
    expect(nameCol.style.width).toBe('300px') // 260 + (140-100), not 260-40
  })

  it('resizes a column by dragging its handle and persists the new width', () => {
    localStorage.removeItem('test-widths')
    const { container } = render(<TestTable storageKey="test-widths" />)

    const handle = container.querySelectorAll('th')[1].querySelector('span')!
    fireEvent.mouseDown(handle, { clientX: 100 })
    fireEvent.mouseMove(window, { clientX: 160 })
    fireEvent.mouseUp(window)

    // AntD applies column width via <colgroup><col>, not the <th> itself.
    const fixedCol = container.querySelectorAll('colgroup col')[1] as HTMLElement
    expect(fixedCol.style.width).toBe('210px') // 150 + (160-100)

    const persisted = JSON.parse(localStorage.getItem('test-widths') ?? '{}')
    expect(persisted.fixed).toBe(210)
  })

  it('loads a previously persisted width on mount', () => {
    localStorage.setItem('test-widths-2', JSON.stringify({ fixed: 300 }))
    const { container } = render(<TestTable storageKey="test-widths-2" />)
    const fixedCol = container.querySelectorAll('colgroup col')[1] as HTMLElement
    expect(fixedCol.style.width).toBe('300px')
  })
})
