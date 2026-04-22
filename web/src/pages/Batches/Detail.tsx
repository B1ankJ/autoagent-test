import {
  App,
  Button,
  Card,
  Descriptions,
  Popconfirm,
  Progress,
  Space,
  Table,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useNavigate, useParams } from 'react-router-dom'
import { statusIsTerminal, useBatchStream, useCancelBatch } from '../../api/batches'
import { DownloadButton } from '../../components/DownloadButton'
import { StatusTag } from '../../components/StatusTag'
import { Sample } from '../../types/api'

export function BatchDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { data, isLoading } = useBatchStream(id)
  const cancel = useCancelBatch()
  const { message } = App.useApp()

  if (isLoading || !data) {
    return <div>加载中...</div>
  }

  const total = data.total
  const completed = data.done + data.failed
  const canCancel = data.status === 'running' || data.status === 'queued'

  const onCancel = async () => {
    try {
      await cancel.mutateAsync(data.batch_id)
      message.success('已请求取消')
    } catch (error) {
      message.error((error as Error).message)
    }
  }

  const sampleColumns: ColumnsType<Sample> = [
    {
      title: 'ID',
      dataIndex: 'id',
      render: (value: string) => (
        <a
          onClick={() => navigate(`/batches/${data.batch_id}/samples/${encodeURIComponent(value)}`)}
        >
          {value}
        </a>
      ),
    },
    {
      title: 'Status',
      dataIndex: 'status',
      render: (status: Sample['status']) => (status ? <StatusTag status={status} /> : '-'),
    },
    {
      title: 'Duration (ms)',
      dataIndex: 'duration_ms',
      render: (value?: number) => value ?? '-',
    },
    {
      title: 'Error',
      dataIndex: 'error',
      render: (value?: string) => (value ? <span title={value}>{value.slice(0, 50)}</span> : '-'),
    },
  ]

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Space style={{ justifyContent: 'space-between', width: '100%' }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          {data.name}
        </Typography.Title>
        <Space>
          <Popconfirm
            title="取消此批次？"
            description="取消后未完成 sample 将中止，已完成结果保留。"
            onConfirm={onCancel}
            disabled={!canCancel}
          >
            <Button danger disabled={!canCancel}>
              取消
            </Button>
          </Popconfirm>
          <DownloadButton batchId={data.batch_id} />
        </Space>
      </Space>
      <Card>
        <Descriptions column={3} bordered size="small">
          <Descriptions.Item label="ID">{data.batch_id}</Descriptions.Item>
          <Descriptions.Item label="Status">
            <StatusTag status={data.status} />
          </Descriptions.Item>
          <Descriptions.Item label="Mode">{data.mode}</Descriptions.Item>
          <Descriptions.Item label="Concurrency">{data.concurrency}</Descriptions.Item>
          <Descriptions.Item label="Started">{data.started_at ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="Finished">{data.ended_at ?? '-'}</Descriptions.Item>
        </Descriptions>
        <Progress
          percent={total ? Math.round((completed / total) * 100) : 0}
          status={statusIsTerminal(data.status) ? 'normal' : 'active'}
          style={{ marginTop: 16 }}
        />
        <div>
          {completed} / {total} 完成（done {data.done}, failed {data.failed}）
        </div>
      </Card>
      <Table<Sample>
        rowKey="id"
        dataSource={data.samples}
        columns={sampleColumns}
        pagination={{ pageSize: 50 }}
      />
    </Space>
  )
}
