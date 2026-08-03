import { App, Button, Segmented, Select, Space, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAcknowledgeAnomaly, useAnomalies } from '../../api/anomalies'
import { EmptyState } from '../../components/states/EmptyState'
import { ErrorState } from '../../components/states/ErrorState'
import { PageHeader } from '../../components/states/PageHeader'
import type { AnomalyRecord, AnomalyType } from '../../types/api'

const TYPE_LABELS: Record<AnomalyType, { label: string; color: string }> = {
  duration: { label: '耗时', color: 'gold' },
  empty_streak: { label: '空响应', color: 'red' },
  same_response: { label: '重复响应', color: 'volcano' },
  anr: { label: 'ANR', color: 'magenta' },
}

export function Anomalies() {
  const navigate = useNavigate()
  const { message } = App.useApp()
  const [typeFilter, setTypeFilter] = useState<AnomalyType | undefined>(undefined)
  const [showAll, setShowAll] = useState(false)
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<number[]>([])
  const [bulkBusy, setBulkBusy] = useState(false)
  const pageSize = 20

  const filters = useMemo(
    () => ({
      type: typeFilter,
      acknowledged: showAll ? undefined : false,
      limit: pageSize,
      offset: (page - 1) * pageSize,
    }),
    [typeFilter, showAll, page],
  )

  const { data, isLoading, isError, refetch } = useAnomalies(filters)
  const ack = useAcknowledgeAnomaly()

  const onAck = async (id: number) => {
    try {
      await ack.mutateAsync(id)
      message.success('已确认')
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  const runBulkAck = async () => {
    setBulkBusy(true)
    try {
      const results = await Promise.allSettled(selected.map((id) => ack.mutateAsync(id)))
      const ok = results.filter((r) => r.status === 'fulfilled').length
      const failed = results.length - ok
      message[failed ? 'warning' : 'success'](
        `已确认 ${ok} 条${failed ? `，${failed} 条失败` : ''}`,
      )
      setSelected([])
    } finally {
      setBulkBusy(false)
    }
  }

  const columns: ColumnsType<AnomalyRecord> = [
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 170,
      render: (v?: string) => (
        <span className="aa-mono" style={{ fontSize: 12 }}>
          {v ? new Date(v).toLocaleString() : '-'}
        </span>
      ),
    },
    {
      title: '类型',
      dataIndex: 'type',
      width: 110,
      render: (t: AnomalyType) => (
        <Tag color={TYPE_LABELS[t]?.color}>{TYPE_LABELS[t]?.label ?? t}</Tag>
      ),
    },
    { title: 'Profile', dataIndex: 'target_profile', width: 140 },
    {
      title: '设备',
      dataIndex: 'device_serial',
      width: 150,
      render: (v?: string | null) => <span className="aa-mono">{v || '-'}</span>,
    },
    { title: '摘要', dataIndex: 'summary' },
    {
      title: '操作',
      width: 150,
      render: (_v, row) => (
        <Space size={4}>
          <a onClick={() => navigate(`/batches/${row.batch_id}/samples/${row.sample_id}`)}>查看</a>
          {!row.acknowledged ? (
            <Button size="small" onClick={() => onAck(row.id)}>
              确认
            </Button>
          ) : (
            <Tag>已确认</Tag>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div>
      <PageHeader title="异常中心" subtitle="统计耗时异常 + 通知规则触发的统一视图" />
      <Space wrap style={{ marginBottom: 12 }}>
        <Select<AnomalyType | 'all'>
          style={{ width: 160 }}
          value={typeFilter ?? 'all'}
          onChange={(v) => {
            setTypeFilter(v === 'all' ? undefined : v)
            setPage(1)
          }}
          options={[
            { value: 'all', label: '全部类型' },
            ...(Object.keys(TYPE_LABELS) as AnomalyType[]).map((t) => ({
              value: t,
              label: TYPE_LABELS[t].label,
            })),
          ]}
        />
        <Segmented
          value={showAll ? 'all' : 'unack'}
          onChange={(v) => {
            setShowAll(v === 'all')
            setPage(1)
          }}
          options={[
            { value: 'unack', label: '未处理' },
            { value: 'all', label: '全部' },
          ]}
        />
        {selected.length > 0 ? (
          <Button size="small" loading={bulkBusy} onClick={runBulkAck}>
            批量确认 ({selected.length})
          </Button>
        ) : null}
      </Space>

      {isError ? (
        <ErrorState title="加载失败" onRetry={() => refetch()} />
      ) : !isLoading && (data?.items.length ?? 0) === 0 ? (
        <EmptyState title="没有异常记录" description="当前筛选下没有异常。" />
      ) : (
        <Table<AnomalyRecord>
          rowKey="id"
          size="small"
          loading={isLoading}
          dataSource={data?.items ?? []}
          columns={columns}
          rowSelection={{
            selectedRowKeys: selected,
            onChange: (keys) => setSelected(keys as number[]),
            getCheckboxProps: (row) => ({ disabled: row.acknowledged }),
          }}
          pagination={{
            current: page,
            pageSize,
            total: data?.total ?? 0,
            onChange: setPage,
            showTotal: (n) => `共 ${n} 条`,
          }}
        />
      )}
    </div>
  )
}
