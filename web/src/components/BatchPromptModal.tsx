import { Alert, Card, Collapse, Empty, Modal, Space, Tag, Typography } from 'antd'
import { useBatch } from '../api/batches'
import { StatusTag } from './StatusTag'
import type { Sample } from '../types/api'

interface Props {
  batchId: string | null
  onClose: () => void
}

/**
 * Quick-look modal showing every sample's prompts and responses inline so
 * users don't have to navigate to the full sample detail just to read
 * what was sent and returned. Used from the Batches list.
 */
export function BatchPromptModal({ batchId, onClose }: Props) {
  const { data, isLoading, error } = useBatch(batchId ?? undefined)

  const samples = data?.samples ?? []
  const singleSample = samples.length === 1

  return (
    <Modal
      open={!!batchId}
      onCancel={onClose}
      footer={null}
      width={820}
      destroyOnClose
      title={
        data ? (
          <Space size={8} wrap>
            <span>{data.name}</span>
            <StatusTag status={data.status} />
            <Typography.Text type="secondary" className="aa-mono" style={{ fontSize: 12 }}>
              {data.batch_id}
            </Typography.Text>
            <Tag>{samples.length} sample{samples.length === 1 ? '' : 's'}</Tag>
          </Space>
        ) : (
          '加载中…'
        )
      }
    >
      {error ? (
        <Alert type="error" message="无法加载批次" description={(error as Error).message} />
      ) : isLoading || !data ? (
        <Typography.Text type="secondary">加载中…</Typography.Text>
      ) : samples.length === 0 ? (
        <Empty description="没有 sample" />
      ) : singleSample ? (
        <SampleBody sample={samples[0]} />
      ) : (
        <Collapse
          accordion={false}
          defaultActiveKey={samples.length <= 5 ? samples.map((s) => s.id) : [samples[0].id]}
          items={samples.map((s, idx) => ({
            key: s.id,
            label: (
              <Space size={6}>
                <span>#{idx + 1}</span>
                <span className="aa-mono" style={{ fontSize: 12 }}>
                  {s.id}
                </span>
                {s.status ? <StatusTag status={s.status} /> : null}
              </Space>
            ),
            children: <SampleBody sample={s} />,
          }))}
        />
      )}
    </Modal>
  )
}

function SampleBody({ sample }: { sample: Sample }) {
  const prompts = sample.prompts_sent ?? []
  const responses = sample.responses ?? []
  const rounds = Math.max(prompts.length, responses.length, 1)

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      {sample.error ? (
        <Alert type="error" showIcon message="Error" description={sample.error} />
      ) : null}
      {Array.from({ length: rounds }, (_, i) => (
        <Card key={i} size="small" title={`第 ${i + 1} 轮`}>
          <div style={{ fontSize: 12, color: 'var(--aa-text-muted)', marginBottom: 4 }}>
            Prompt
          </div>
          <Typography.Paragraph
            style={{ whiteSpace: 'pre-wrap', margin: 0, marginBottom: 12 }}
            copyable={!!prompts[i]}
          >
            {prompts[i] ?? <Typography.Text type="secondary">(空)</Typography.Text>}
          </Typography.Paragraph>
          <div style={{ fontSize: 12, color: 'var(--aa-text-muted)', marginBottom: 4 }}>
            Response
          </div>
          <Typography.Paragraph
            style={{ whiteSpace: 'pre-wrap', margin: 0 }}
            copyable={!!responses[i]}
          >
            {responses[i] || <Typography.Text type="secondary">(无响应)</Typography.Text>}
          </Typography.Paragraph>
        </Card>
      ))}
    </Space>
  )
}
