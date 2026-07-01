import { ArrowLeftOutlined, DownloadOutlined, LeftOutlined, RightOutlined } from '@ant-design/icons'
import { Button, Card, Collapse, Descriptions, Space, Table, Typography } from 'antd'
import { useCallback, useEffect, useMemo } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { downloadSampleLogs } from '../../api/batches'
import { useBatchStream } from '../../hooks/useBatchStream'
import { ResponseComparison } from '../../components/ResponseComparison'
import { ScreenshotStrip } from '../../components/ScreenshotStrip'
import { StatusTag } from '../../components/StatusTag'
import { EmptyState } from '../../components/states/EmptyState'
import { PageHeader } from '../../components/states/PageHeader'
import { PageSkeleton } from '../../components/states/PageSkeleton'
import { hasLLMExtractionData } from '../../utils/llmExtraction'

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
  const decodedSid = decodeURIComponent(sid ?? '')
  const sample = data?.samples.find((item) => item.id === decodedSid)
  const promptRounds = sample?.prompts ?? sample?.prompts_sent ?? []
  const summary = metadataSummary(sample?.metadata)
  const llmEnabled = hasLLMExtractionData(sample?.llm_responses, sample?.llm_errors)

  // Prev/next navigation: use the batch's sample order as-is (matches what
  // the batch detail table shows). At the head/tail the neighbor is null.
  const { prev, next } = useMemo(() => {
    const list = data?.samples ?? []
    const idx = list.findIndex((s) => s.id === decodedSid)
    if (idx < 0) return { prev: null, next: null }
    return {
      prev: idx > 0 ? list[idx - 1] : null,
      next: idx < list.length - 1 ? list[idx + 1] : null,
    }
  }, [data?.samples, decodedSid])

  const goTo = useCallback(
    (target: { id: string } | null) => {
      if (!target || !id) return
      navigate(`/batches/${id}/samples/${encodeURIComponent(target.id)}`)
    },
    [id, navigate],
  )

  // Keyboard nav: j = next, k = prev. Skip when a text input owns focus so
  // we don't fight with prompt-search boxes / textareas.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      const tag = el?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || el?.isContentEditable) return
      if (e.metaKey || e.ctrlKey || e.altKey) return
      if (e.key === 'j') {
        e.preventDefault()
        goTo(next)
      } else if (e.key === 'k') {
        e.preventDefault()
        goTo(prev)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [goTo, prev, next])

  const breadcrumb = (
    <Space size={6}>
      <a onClick={() => navigate(`/batches/${id}`)} style={{ color: 'var(--aa-text-muted)' }}>
        <ArrowLeftOutlined /> 批次
      </a>
      <span>/ Sample</span>
    </Space>
  )

  if (!data) {
    return (
      <div>
        <PageHeader eyebrow={breadcrumb} title="加载中…" />
        <PageSkeleton rows={6} />
      </div>
    )
  }

  if (!sample) {
    return (
      <div>
        <PageHeader eyebrow={breadcrumb} title="Sample 未找到" />
        <EmptyState
          title="Sample 不存在"
          description="可能已被清理,或 sample ID 拼写错了。"
          action={<Button onClick={() => navigate(`/batches/${id}`)}>返回批次</Button>}
        />
      </div>
    )
  }

  const replayAvailable = !!sample.metadata?.action_replay_available

  return (
    <div>
      <PageHeader
        eyebrow={breadcrumb}
        title={<span className="aa-mono">{sample.id}</span>}
        subtitle={
          <Space size={10}>
            {sample.status ? <StatusTag status={sample.status} /> : null}
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {sample.target_profile}
            </Typography.Text>
          </Space>
        }
        extra={
          <Space>
            <Button
              size="small"
              icon={<LeftOutlined />}
              disabled={!prev}
              onClick={() => goTo(prev)}
              title={prev ? `上一个 (k): ${prev.id}` : '已是第一个'}
            >
              上一个
            </Button>
            <Button
              size="small"
              icon={<RightOutlined />}
              disabled={!next}
              onClick={() => goTo(next)}
              title={next ? `下一个 (j): ${next.id}` : '已是最后一个'}
            >
              下一个
            </Button>
            {replayAvailable ? (
              <Button
                icon={<DownloadOutlined />}
                onClick={() => downloadSampleLogs(data.batch_id, sample.id)}
                title="zip 包含 actions.jsonl + 截图 + XML + executor.log 等全部产物"
              >
                下载日志包
              </Button>
            ) : null}
          </Space>
        }
      />

      <Card size="small" style={{ marginBottom: 16 }}>
        <Descriptions column={2} size="small" colon={false} labelStyle={{ color: 'var(--aa-text-muted)' }}>
          <Descriptions.Item label="耗时 (ms)">
            <span className="aa-mono" style={{ fontVariantNumeric: 'tabular-nums' }}>
              {sample.duration_ms ?? '-'}
            </span>
          </Descriptions.Item>
          <Descriptions.Item label="New session">
            {String(sample.new_session ?? false)}
          </Descriptions.Item>
          <Descriptions.Item label="运行设备">
            <span className="aa-mono">
              {sample.device_serial ?? (sample.metadata?.device_serial as string | undefined) ?? '-'}
            </span>
          </Descriptions.Item>
          <Descriptions.Item label="等待设备">
            {String(sample.waiting_for_device ?? false)}
          </Descriptions.Item>
          {sample.started_at ? (
            <Descriptions.Item label="开始">
              <span className="aa-mono">{sample.started_at}</span>
            </Descriptions.Item>
          ) : null}
          {sample.ended_at ? (
            <Descriptions.Item label="结束">
              <span className="aa-mono">{sample.ended_at}</span>
            </Descriptions.Item>
          ) : null}
        </Descriptions>
      </Card>

      {sample.error ? (
        <Card size="small" title="Error" style={{ marginBottom: 16 }}>
          <Typography.Paragraph type="danger" style={{ margin: 0 }}>
            {sample.error}
          </Typography.Paragraph>
        </Card>
      ) : null}

      <Card size="small" title="Prompts + Responses" style={{ marginBottom: 16 }}>
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

      <Card size="small" title="截图" style={{ marginBottom: 16 }}>
        <ScreenshotStrip batchId={data.batch_id} sampleId={sample.id} />
      </Card>

      {Array.isArray(sample.metadata?.action_log) && sample.metadata.action_log.length ? (
        <Card size="small" title="动作日志" style={{ marginBottom: 16 }}>
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
        <Card size="small" title="Metadata">
          <Descriptions
            column={2}
            size="small"
            colon={false}
            labelStyle={{ color: 'var(--aa-text-muted)' }}
            style={{ marginBottom: 12 }}
          >
            <Descriptions.Item label="设备序列号">
              <span className="aa-mono">{summary.deviceSerial}</span>
            </Descriptions.Item>
            <Descriptions.Item label="截图数量">{summary.screenshots}</Descriptions.Item>
            <Descriptions.Item label="动作数">{summary.actionLog}</Descriptions.Item>
            <Descriptions.Item label="可下载回放">{summary.replay}</Descriptions.Item>
          </Descriptions>
          <pre
            className="aa-mono"
            style={{
              margin: 0,
              padding: 12,
              background: 'var(--aa-surface-alt)',
              border: '1px solid var(--aa-border)',
              borderRadius: 6,
              fontSize: 11,
              maxHeight: 320,
              overflow: 'auto',
            }}
          >
            {JSON.stringify(sample.metadata, null, 2)}
          </pre>
        </Card>
      ) : null}
    </div>
  )
}
