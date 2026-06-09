import { ArrowLeftOutlined, ExperimentOutlined } from '@ant-design/icons'
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
import { EmptyState } from '../../components/states/EmptyState'
import { PageHeader } from '../../components/states/PageHeader'
import { PageSkeleton } from '../../components/states/PageSkeleton'
import { Sample } from '../../types/api'

export function BatchDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { data, isLoading } = useBatchStream(id)
  const cancel = useCancelBatch()
  const { message } = App.useApp()

  if (isLoading || !data) {
    return (
      <div>
        <PageHeader eyebrow="任务 / 批次" title="加载中…" />
        <PageSkeleton rows={6} />
      </div>
    )
  }

  const total = data.total
  const completed = data.done + data.failed
  const canCancel = data.status === 'running' || data.status === 'queued'
  const percent = total ? Math.round((completed / total) * 100) : 0

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
          className="aa-mono"
          onClick={() => navigate(`/batches/${data.batch_id}/samples/${encodeURIComponent(value)}`)}
        >
          {value}
        </a>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (status: Sample['status']) => (status ? <StatusTag status={status} /> : '-'),
    },
    {
      title: '耗时 (ms)',
      dataIndex: 'duration_ms',
      width: 120,
      render: (value?: number) => (
        <span className="aa-mono aa-muted" style={{ fontVariantNumeric: 'tabular-nums' }}>
          {value ?? '-'}
        </span>
      ),
    },
    {
      title: '错误',
      dataIndex: 'error',
      render: (value?: string) =>
        value ? (
          <span className="aa-mono" title={value} style={{ color: 'var(--aa-amber)' }}>
            {value.slice(0, 80)}
          </span>
        ) : (
          <span className="aa-muted">-</span>
        ),
    },
  ]

  return (
    <div>
      <PageHeader
        eyebrow={
          <Space size={6}>
            <a
              onClick={() => navigate('/batches')}
              style={{ color: 'var(--aa-text-muted)' }}
            >
              <ArrowLeftOutlined /> 批次
            </a>
            <span>/ 详情</span>
          </Space>
        }
        title={data.name}
        subtitle={
          <span className="aa-mono aa-muted" style={{ fontSize: 12 }}>
            {data.batch_id}
          </span>
        }
        extra={
          <>
            <Popconfirm
              title="取消此批次?"
              description="取消后未完成 sample 将中止,已完成结果保留。"
              onConfirm={onCancel}
              disabled={!canCancel}
            >
              <Button danger disabled={!canCancel}>
                取消
              </Button>
            </Popconfirm>
            <DownloadButton batchId={data.batch_id} />
          </>
        }
      />

      <Card size="small" style={{ marginBottom: 16 }}>
        <Descriptions column={3} size="small" colon={false} labelStyle={{ color: 'var(--aa-text-muted)' }}>
          <Descriptions.Item label="状态">
            <StatusTag status={data.status} />
          </Descriptions.Item>
          <Descriptions.Item label="模式">{data.mode}</Descriptions.Item>
          <Descriptions.Item label="并发">{data.concurrency}</Descriptions.Item>
          <Descriptions.Item label="开始时间">
            <span className="aa-mono">{data.started_at ?? '-'}</span>
          </Descriptions.Item>
          <Descriptions.Item label="结束时间">
            <span className="aa-mono">{data.ended_at ?? '-'}</span>
          </Descriptions.Item>
          <Descriptions.Item label="进度">
            <span className="aa-mono" style={{ fontVariantNumeric: 'tabular-nums' }}>
              {completed} / {total}
            </span>
          </Descriptions.Item>
        </Descriptions>
        <Progress
          percent={percent}
          status={statusIsTerminal(data.status) ? 'normal' : 'active'}
          style={{ marginTop: 12 }}
        />
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          done {data.done} · failed {data.failed}
        </Typography.Text>
      </Card>

      {data.samples.length === 0 ? (
        <EmptyState
          icon={<ExperimentOutlined />}
          title="还没有 sample 结果"
          description="批次刚启动时这里是空的;sample 完成后会立即显示。"
        />
      ) : (
        <Table<Sample>
          rowKey="id"
          size="small"
          dataSource={data.samples}
          columns={sampleColumns}
          pagination={{ pageSize: 50, showSizeChanger: true }}
        />
      )}
    </div>
  )
}
