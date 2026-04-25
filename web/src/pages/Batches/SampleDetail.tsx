import { Button, Card, Collapse, Descriptions, Space, Table, Typography } from 'antd'
import { useNavigate, useParams } from 'react-router-dom'
import { downloadSampleActions } from '../../api/batches'
import { useBatchStream } from '../../hooks/useBatchStream'
import { ResponseComparison } from '../../components/ResponseComparison'
import { ScreenshotStrip } from '../../components/ScreenshotStrip'
import { StatusTag } from '../../components/StatusTag'

function formatLocator(locator: unknown): string {
  if (!locator || typeof locator !== 'object') return '-'
  const maybeLocator = locator as { type?: unknown; value?: unknown }
  if (typeof maybeLocator.type === 'string' && typeof maybeLocator.value === 'string') {
    return `${maybeLocator.type}:${maybeLocator.value}`
  }
  return '-'
}

function formatActionTarget(record: Record<string, unknown>): string {
  if (typeof record.x === 'number' && typeof record.y === 'number') {
    return `(${record.x}, ${record.y})`
  }
  if (record.locator) {
    return formatLocator(record.locator)
  }
  if (typeof record.url === 'string') {
    return record.url
  }
  if (
    typeof record.x1 === 'number' &&
    typeof record.y1 === 'number' &&
    typeof record.x2 === 'number' &&
    typeof record.y2 === 'number'
  ) {
    return `(${record.x1}, ${record.y1}) -> (${record.x2}, ${record.y2})`
  }
  if (typeof record.key === 'string') {
    return record.key
  }
  if (typeof record.package === 'string' && typeof record.activity === 'string') {
    return `${record.package}/${record.activity}`
  }
  if (typeof record.package === 'string') {
    return record.package
  }
  return '-'
}

function metadataSummary(metadata: Record<string, unknown> | undefined) {
  const screenshots = Array.isArray(metadata?.screenshots) ? metadata.screenshots.length : 0
  const actionLog = Array.isArray(metadata?.action_log) ? metadata.action_log.length : 0
  return {
    deviceSerial: typeof metadata?.device_serial === 'string' ? metadata.device_serial : '-',
    screenshots,
    actionLog,
    replay: metadata?.action_replay_available ? '是' : '否',
  }
}

export function SampleDetail() {
  const { id, sid } = useParams()
  const navigate = useNavigate()
  const { data } = useBatchStream(id)
  const sample = data?.samples.find((item) => item.id === decodeURIComponent(sid ?? ''))
  const promptRounds = sample?.prompts ?? sample?.prompts_sent ?? []
  const summary = metadataSummary(sample?.metadata)
  const llmEnabled = !!(sample?.llm_responses || sample?.llm_errors)

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
          <Descriptions.Item label="运行设备">
            {sample.device_serial ?? (sample.metadata?.device_serial as string | undefined) ?? '-'}
          </Descriptions.Item>
          <Descriptions.Item label="等待设备">
            {String(sample.waiting_for_device ?? false)}
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
          defaultActiveKey={promptRounds.map((_, index) => String(index))}
          items={promptRounds.map((prompt, index) => ({
            key: String(index),
            forceRender: true,
            label: `第 ${index + 1} 轮`,
            children: (
              <Space direction="vertical" style={{ width: '100%' }}>
                <div>
                  <strong>Prompt:</strong>
                </div>
                <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>
                  {prompt}
                </Typography.Paragraph>
                <ResponseComparison
                  ruleResponse={sample.responses?.[index]}
                  llmResponse={sample.llm_responses?.[index]}
                  llmError={sample.llm_errors?.[index]}
                  llmEnabled={llmEnabled}
                />
              </Space>
            ),
          }))}
        />
      </Card>

      <Card title="截图">
        <ScreenshotStrip batchId={data.batch_id} sampleId={sample.id} />
      </Card>

      {sample.metadata?.action_replay_available ? (
        <Button onClick={() => downloadSampleActions(data.batch_id, sample.id)}>
          下载回放 JSONL
        </Button>
      ) : null}

      {Array.isArray(sample.metadata?.action_log) && sample.metadata.action_log.length ? (
        <Card title="动作日志">
          <Table
            size="small"
            rowKey={(record) =>
              `${String(record.action ?? 'action')}-${String(record.t_ms ?? '-')}-${formatActionTarget(record)}`
            }
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
                render: (_value: unknown, record: Record<string, unknown>) => formatActionTarget(record),
              },
              {
                title: 'Result',
                render: (_value: unknown, record: Record<string, unknown>) =>
                  record.ok === false ? `failed: ${String(record.error ?? '-')}` : 'ok',
              },
              {
                title: 't_ms',
                dataIndex: 't_ms',
                render: (value?: number) => value ?? '-',
              },
            ]}
          />
        </Card>
      ) : null}

      {sample.metadata ? (
        <Card title="Metadata">
          <Descriptions column={2} bordered size="small" style={{ marginBottom: 16 }}>
            <Descriptions.Item label="设备序列号">{summary.deviceSerial}</Descriptions.Item>
            <Descriptions.Item label="截图数量">{summary.screenshots}</Descriptions.Item>
            <Descriptions.Item label="动作数">{summary.actionLog}</Descriptions.Item>
            <Descriptions.Item label="可下载回放">{summary.replay}</Descriptions.Item>
          </Descriptions>
          <pre>{JSON.stringify(sample.metadata, null, 2)}</pre>
        </Card>
      ) : null}
    </Space>
  )
}
