import { PlusOutlined } from '@ant-design/icons'
import { Button, Empty, Select, Space, Table, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useBatches } from '../../api/batches'
import { ModeTag } from '../../components/ModeTag'
import { StatusTag } from '../../components/StatusTag'
import { BatchStatus, BatchSummary, ExecutionMode } from '../../types/api'

export function BatchList() {
  const navigate = useNavigate()
  const { data, isLoading } = useBatches()
  const [statusFilter, setStatusFilter] = useState<BatchStatus | undefined>()
  const [modeFilter, setModeFilter] = useState<ExecutionMode | undefined>()

  const rows = (data ?? []).filter(
    (batch) =>
      (!statusFilter || batch.status === statusFilter) &&
      (!modeFilter || batch.mode === modeFilter),
  )

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
      <Space>
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
          pagination={{ pageSize: 20 }}
        />
      )}
    </Space>
  )
}
