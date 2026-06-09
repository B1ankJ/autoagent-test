import { PlusOutlined, ExperimentOutlined } from '@ant-design/icons'
import { Button, Input, Select, Space, Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useBatches, useBatchStats } from '../../api/batches'
import { ModeTag } from '../../components/ModeTag'
import { StatusTag } from '../../components/StatusTag'
import { EmptyState } from '../../components/states/EmptyState'
import { ErrorState } from '../../components/states/ErrorState'
import { PageHeader } from '../../components/states/PageHeader'
import { BatchStatus, BatchSummary, ExecutionMode } from '../../types/api'

export function BatchList() {
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [searchInput, setSearchInput] = useState('')
  const [debouncedQ, setDebouncedQ] = useState('')

  useEffect(() => {
    const handle = setTimeout(() => {
      setDebouncedQ(searchInput.trim())
      setPage(1)
    }, 300)
    return () => clearTimeout(handle)
  }, [searchInput])

  const { data, isLoading, isError, error, refetch } = useBatches({
    limit: pageSize,
    offset: (page - 1) * pageSize,
    q: debouncedQ,
  })
  const { data: stats } = useBatchStats({ q: debouncedQ })
  const [statusFilter, setStatusFilter] = useState<BatchStatus | undefined>()
  const [modeFilter, setModeFilter] = useState<ExecutionMode | undefined>()

  const rows = useMemo(
    () =>
      (data ?? []).filter(
        (batch) =>
          (!statusFilter || batch.status === statusFilter) &&
          (!modeFilter || batch.mode === modeFilter),
      ),
    [data, statusFilter, modeFilter],
  )
  const total = stats?.total ?? 0

  const columns: ColumnsType<BatchSummary> = [
    {
      title: '名称',
      dataIndex: 'name',
      render: (value: string, row) => (
        <a onClick={() => navigate(`/batches/${row.batch_id}`)}>{value}</a>
      ),
    },
    {
      title: '模式',
      dataIndex: 'mode',
      width: 140,
      render: (mode: ExecutionMode) => <ModeTag mode={mode} />,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (status: BatchStatus) => <StatusTag status={status} />,
    },
    {
      title: '进度',
      width: 110,
      render: (_value, row) => (
        <span className="aa-mono">
          {row.done + row.failed}/{row.total}
        </span>
      ),
    },
    {
      title: '开始时间',
      dataIndex: 'started_at',
      width: 200,
      render: (value?: string) => (
        <span className="aa-mono aa-muted">{value ?? '-'}</span>
      ),
    },
  ]

  return (
    <div>
      <PageHeader
        eyebrow="任务"
        title="批次 Batches"
        subtitle={
          total > 0
            ? `共 ${total} 个批次${debouncedQ ? `,匹配 "${debouncedQ}"` : ''}`
            : undefined
        }
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/batches/new')}>
            新建批次
          </Button>
        }
      />
      <Space wrap style={{ marginBottom: 14 }}>
        <Input.Search
          placeholder="搜索批次名 / ID / Prompt 内容"
          allowClear
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          style={{ width: 340 }}
        />
        <Select
          allowClear
          placeholder="状态"
          style={{ width: 140 }}
          value={statusFilter}
          onChange={setStatusFilter}
          options={['queued', 'running', 'done', 'failed', 'cancelled'].map((status) => ({
            value: status,
            label: status,
          }))}
        />
        <Select
          allowClear
          placeholder="模式"
          style={{ width: 170 }}
          value={modeFilter}
          onChange={setModeFilter}
          options={['api', 'gui_pc_web', 'gui_android', 'agent_pc', 'agent_android'].map(
            (mode) => ({
              value: mode,
              label: mode,
            }),
          )}
        />
      </Space>
      {isError ? (
        <ErrorState
          description="无法读取批次列表"
          detail={error instanceof Error ? error.message : undefined}
          onRetry={() => refetch()}
        />
      ) : rows.length === 0 && !isLoading ? (
        <EmptyState
          icon={<ExperimentOutlined />}
          title={debouncedQ ? '没有匹配的批次' : '还没有批次'}
          description={
            debouncedQ
              ? '换个关键字,或清空搜索看全部。'
              : '创建第一个批次开始批量测试。'
          }
          action={
            <Button type="primary" onClick={() => navigate('/batches/new')}>
              新建批次
            </Button>
          }
        />
      ) : (
        <Table<BatchSummary>
          rowKey="batch_id"
          size="small"
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
    </div>
  )
}
