import { PlusOutlined } from '@ant-design/icons'
import { Button, Empty, Input, Select, Space, Table, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useBatches, useBatchStats } from '../../api/batches'
import { ModeTag } from '../../components/ModeTag'
import { StatusTag } from '../../components/StatusTag'
import { BatchStatus, BatchSummary, ExecutionMode } from '../../types/api'

export function BatchList() {
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [searchInput, setSearchInput] = useState('')
  const [debouncedQ, setDebouncedQ] = useState('')

  // Debounce search input so each keystroke doesn't fire a query.
  useEffect(() => {
    const handle = setTimeout(() => {
      setDebouncedQ(searchInput.trim())
      setPage(1)
    }, 300)
    return () => clearTimeout(handle)
  }, [searchInput])

  const { data, isLoading } = useBatches({
    limit: pageSize,
    offset: (page - 1) * pageSize,
    q: debouncedQ,
  })
  const { data: stats } = useBatchStats({ q: debouncedQ })
  const [statusFilter, setStatusFilter] = useState<BatchStatus | undefined>()
  const [modeFilter, setModeFilter] = useState<ExecutionMode | undefined>()

  // Filters run on the current page only — the backend doesn't filter yet.
  // The total reflects the unfiltered server-side count so pagination stays
  // honest; if the user filters, partial pages are an accepted trade-off.
  const rows = (data ?? []).filter(
    (batch) =>
      (!statusFilter || batch.status === statusFilter) &&
      (!modeFilter || batch.mode === modeFilter),
  )
  const total = stats?.total ?? 0

  const columns: ColumnsType<BatchSummary> = [
    {
      title: 'Name',
      dataIndex: 'name',
      render: (value: string, row) => (
        <a onClick={() => navigate(`/batches/${row.batch_id}`)}>{value}</a>
      ),
    },
    {
      title: 'Mode',
      dataIndex: 'mode',
      render: (mode: ExecutionMode) => <ModeTag mode={mode} />,
    },
    {
      title: 'Status',
      dataIndex: 'status',
      render: (status: BatchStatus) => <StatusTag status={status} />,
    },
    {
      title: 'Progress',
      render: (_value, row) => `${row.done + row.failed}/${row.total}`,
    },
    {
      title: 'Started',
      dataIndex: 'started_at',
      render: (value?: string) => value ?? '-',
    },
  ]

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Space style={{ justifyContent: 'space-between', width: '100%' }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          Batches
        </Typography.Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/batches/new')}>
          新建批次
        </Button>
      </Space>
      <Space wrap>
        <Input.Search
          placeholder="搜索批次名/ID/Prompt 内容"
          allowClear
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          style={{ width: 320 }}
        />
        <Select
          allowClear
          placeholder="Status"
          style={{ width: 160 }}
          value={statusFilter}
          onChange={setStatusFilter}
          options={['queued', 'running', 'done', 'failed', 'cancelled'].map((status) => ({
            value: status,
            label: status,
          }))}
        />
        <Select
          allowClear
          placeholder="Mode"
          style={{ width: 180 }}
          value={modeFilter}
          onChange={setModeFilter}
          options={['api', 'gui_pc_web', 'gui_android'].map((mode) => ({
            value: mode,
            label: mode,
          }))}
        />
      </Space>
      {rows.length === 0 && !isLoading ? (
        <Empty
          description={
            <Space direction="vertical">
              <div>还没有批次</div>
              <Button type="primary" onClick={() => navigate('/batches/new')}>
                创建第一个批次
              </Button>
            </Space>
          }
        />
      ) : (
        <Table<BatchSummary>
          rowKey="batch_id"
          loading={isLoading}
          dataSource={rows}
          columns={columns}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            pageSizeOptions: ['20', '50', '100', '200'],
            showTotal: (n) => `共 ${n} 条`,
            onChange: (p, ps) => {
              setPage(p)
              setPageSize(ps)
            },
          }}
        />
      )}
    </Space>
  )
}
