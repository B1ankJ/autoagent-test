import { Card, Col, Row, Space, Statistic, Table, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useNavigate } from 'react-router-dom'
import { useBatches } from '../api/batches'
import { StatusTag } from '../components/StatusTag'
import { BatchStatus, BatchSummary } from '../types/api'

export function Dashboard() {
  const navigate = useNavigate()
  const { data } = useBatches()
  const batches = data ?? []
  const byStatus: Record<BatchStatus, number> = {
    queued: 0,
    running: 0,
    done: 0,
    failed: 0,
    cancelled: 0,
  }

  for (const batch of batches) {
    byStatus[batch.status] += 1
  }

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
            <Statistic title="Total" value={batches.length} />
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
