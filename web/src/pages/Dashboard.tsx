import { Card, Col, Row, Space, Statistic, Table, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useNavigate } from 'react-router-dom'
import { useBatches, useBatchStats } from '../api/batches'
import { StatusTag } from '../components/StatusTag'
import { BatchStatus, BatchSummary } from '../types/api'

export function Dashboard() {
  const navigate = useNavigate()
  const { data } = useBatches({ limit: 10 })
  const { data: stats } = useBatchStats()
  const batches = data ?? []
  const byStatus = {
    queued: stats?.queued ?? 0,
    running: stats?.running ?? 0,
    done: stats?.done ?? 0,
    failed: stats?.failed ?? 0,
    cancelled: stats?.cancelled ?? 0,
  }
  const total = stats?.total ?? batches.length

  const recent = [...batches].slice(0, 10)
  const columns: ColumnsType<BatchSummary> = [
    {
      title: 'Name',
      dataIndex: 'name',
      render: (value: string, row) => (
        <a onClick={() => navigate(`/batches/${row.batch_id}`)}>{value}</a>
      ),
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
  ]

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Typography.Title level={3}>Dashboard</Typography.Title>
      <Row gutter={16}>
        <Col span={4}>
          <Card>
            <Statistic title="Total" value={total} />
          </Card>
        </Col>
        <Col span={4}>
          <Card>
            <Statistic title="Running" value={byStatus.running} />
          </Card>
        </Col>
        <Col span={4}>
          <Card>
            <Statistic title="Done" value={byStatus.done} />
          </Card>
        </Col>
        <Col span={4}>
          <Card>
            <Statistic title="Failed" value={byStatus.failed} />
          </Card>
        </Col>
        <Col span={4}>
          <Card>
            <Statistic title="Cancelled" value={byStatus.cancelled} />
          </Card>
        </Col>
        <Col span={4}>
          <Card>
            <Statistic title="Queued" value={byStatus.queued} />
          </Card>
        </Col>
      </Row>
      <Card title="最近批次">
        <Table<BatchSummary>
          rowKey="batch_id"
          dataSource={recent}
          columns={columns}
          pagination={false}
        />
      </Card>
    </Space>
  )
}
