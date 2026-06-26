import { PlusOutlined, ExperimentOutlined, StopOutlined } from '@ant-design/icons'
import { App, Button, Input, Popconfirm, Select, Space, Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useBatches, useBatchStats, useCancelActiveBatches } from '../../api/batches'
import { ModeTag } from '../../components/ModeTag'
import { StatusTag } from '../../components/StatusTag'
import { EmptyState } from '../../components/states/EmptyState'
import { ErrorState } from '../../components/states/ErrorState'
import { PageHeader } from '../../components/states/PageHeader'
import { BatchStatus, BatchSummary, ExecutionMode } from '../../types/api'

// Filter state is mirrored to the URL query so refresh / share / back-button
// all retain the user's view. Keys are intentionally short to keep URLs scannable.
const QP_Q = 'q'
const QP_STATUS = 'status'
const QP_MODE = 'mode'
const QP_PAGE = 'page'
const QP_SIZE = 'size'

export function BatchList() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { message } = App.useApp()
  const cancelActive = useCancelActiveBatches()

  const page = Math.max(1, parseInt(searchParams.get(QP_PAGE) ?? '1', 10) || 1)
  const pageSize = parseInt(searchParams.get(QP_SIZE) ?? '20', 10) || 20
  const debouncedQ = searchParams.get(QP_Q) ?? ''
  const statusFilter = (searchParams.get(QP_STATUS) as BatchStatus | null) || undefined
  const modeFilter = (searchParams.get(QP_MODE) as ExecutionMode | null) || undefined

  // Local-only input mirror so typing doesn't trigger a URL/query write on
  // every keystroke; commit to URL after a 300ms debounce.
  const [searchInput, setSearchInput] = useState(debouncedQ)

  // Apply multiple param changes in ONE navigate. Back-to-back
  // setSearchParams() calls race because each reads the URL fresh, so the
  // second navigate silently overwrites the first — losing fields.
  const updateParams = (changes: Record<string, string | undefined>) => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        for (const [key, value] of Object.entries(changes)) {
          if (value === undefined || value === '') next.delete(key)
          else next.set(key, value)
        }
        return next
      },
      { replace: true },
    )
  }
  const setStatusFilter = (v: BatchStatus | undefined) => {
    updateParams({ [QP_STATUS]: v, [QP_PAGE]: undefined })
  }
  const setModeFilter = (v: ExecutionMode | undefined) => {
    updateParams({ [QP_MODE]: v, [QP_PAGE]: undefined })
  }
  const setPagination = (p: number, ps: number) => {
    updateParams({
      [QP_PAGE]: p === 1 ? undefined : String(p),
      [QP_SIZE]: ps === 20 ? undefined : String(ps),
    })
  }

  useEffect(() => {
    const handle = setTimeout(() => {
      const trimmed = searchInput.trim()
      if (trimmed !== debouncedQ) {
        updateParams({ [QP_Q]: trimmed || undefined, [QP_PAGE]: undefined })
      }
    }, 300)
    return () => clearTimeout(handle)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchInput])

  const { data, isLoading, isError, error, refetch } = useBatches({
    limit: pageSize,
    offset: (page - 1) * pageSize,
    q: debouncedQ,
  })
  const { data: stats } = useBatchStats({ q: debouncedQ })

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
  const activeCount = (stats?.queued ?? 0) + (stats?.running ?? 0)

  const onCancelActive = async () => {
    try {
      const result = await cancelActive.mutateAsync()
      const parts: string[] = []
      if (result.cancelled > 0) parts.push(`已取消 ${result.cancelled} 个进行中批次`)
      if (result.orphaned > 0) parts.push(`已清理 ${result.orphaned} 个孤儿状态`)
      message.success(parts.length ? parts.join('，') : '没有需要取消的批次')
    } catch (e) {
      message.error((e as Error).message)
    }
  }

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
          <Space>
            <Popconfirm
              title="取消所有进行中批次"
              description={
                activeCount > 0
                  ? `当前有 ${activeCount} 个 queued/running 批次，全部停掉？`
                  : '当前没有进行中的批次（仅清理可能的孤儿状态）。'
              }
              onConfirm={onCancelActive}
              okText="取消全部"
              cancelText="不"
              disabled={cancelActive.isPending}
            >
              <Button
                danger
                icon={<StopOutlined />}
                loading={cancelActive.isPending}
                disabled={activeCount === 0 && !cancelActive.isPending}
              >
                取消全部 {activeCount > 0 ? `(${activeCount})` : ''}
              </Button>
            </Popconfirm>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/batches/new')}>
              新建批次
            </Button>
          </Space>
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
            onChange: setPagination,
          }}
        />
      )}
    </div>
  )
}
