import { Button, Card, Collapse, Descriptions, Space, Table, Typography } from 'antd'
import { useNavigate, useParams } from 'react-router-dom'
import { useBatchStream } from '../../hooks/useBatchStream'
import { ScreenshotStrip } from '../../components/ScreenshotStrip'
import { StatusTag } from '../../components/StatusTag'

export function SampleDetail() {
  const { id, sid } = useParams()
  const navigate = useNavigate()
  const { data } = useBatchStream(id)
  const sample = data?.samples.find((item) => item.id === decodeURIComponent(sid ?? ''))

  if (!data) {
    return <div>加载中...</div>
  }

  if (!sample) {
    return (
      <div>
        Sample 不存在 <Button onClick={() => navigate(`/batches/${id}`)}>返回批次</Button>
      </div>
    )
  }

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Space>
        <Button onClick={() => navigate(`/batches/${id}`)}>← 返回批次</Button>
        <Typography.Title level={3} style={{ margin: 0 }}>
          Sample {sample.id}
        </Typography.Title>
      </Space>
      <Card>
        <Descriptions column={2} bordered size="small">
          <Descriptions.Item label="Status">
            {sample.status ? <StatusTag status={sample.status} /> : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="Profile">{sample.target_profile}</Descriptions.Item>
          <Descriptions.Item label="Duration (ms)">{sample.duration_ms ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="New session">
            {String(sample.new_session ?? false)}
          </Descriptions.Item>
          {sample.started_at ? (
            <Descriptions.Item label="Started">{sample.started_at}</Descriptions.Item>
          ) : null}
          {sample.ended_at ? (
            <Descriptions.Item label="Finished">{sample.ended_at}</Descriptions.Item>
          ) : null}
        </Descriptions>
      </Card>

      {sample.error ? (
        <Card title="Error">
          <Typography.Paragraph type="danger">{sample.error}</Typography.Paragraph>
        </Card>
      ) : null}

      <Card title="Prompts + Responses">
        <Collapse
          items={sample.prompts.map((prompt, index) => ({
            key: String(index),
            label: `第 ${index + 1} 轮`,
            children: (
              <Space direction="vertical" style={{ width: '100%' }}>
                <div>
                  <strong>Prompt:</strong>
                </div>
                <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>
                  {prompt}
                </Typography.Paragraph>
                <div>
                  <strong>Response:</strong>
                </div>
                <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>
                  {sample.responses?.[index] ?? '(无响应)'}
                </Typography.Paragraph>
              </Space>
            ),
          }))}
        />
      </Card>

      <Card title="截图">
        <ScreenshotStrip batchId={data.batch_id} sampleId={sample.id} />
      </Card>

      {Array.isArray(sample.metadata?.action_log) && sample.metadata.action_log.length ? (
        <Card title="动作日志">
          <Table
            size="small"
            rowKey={(_record, index) => String(index)}
            pagination={false}
            dataSource={sample.metadata.action_log as Array<Record<string, unknown>>}
            columns={[
              {
                title: 'Action',
                dataIndex: 'action',
                render: (value?: string) => value ?? '-',
              },
              {
                title: 'Target',
                dataIndex: 'selector',
                render: (value?: string, record?: Record<string, unknown>) =>
                  value ?? (record?.url as string | undefined) ?? '-',
              },
            ]}
          />
        </Card>
      ) : null}

      {sample.metadata ? (
        <Card title="Metadata">
          <pre>{JSON.stringify(sample.metadata, null, 2)}</pre>
        </Card>
      ) : null}
    </Space>
  )
}
