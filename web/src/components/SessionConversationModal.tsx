import { Empty, Modal, Space, Spin, Typography } from 'antd'
import type { CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'

import { useSessionConversation } from '../api/batches'
import { ScreenshotStrip } from './ScreenshotStrip'
import { StatusTag } from './StatusTag'

const FIELD_LABEL_STYLE: CSSProperties = {
  display: 'block',
  fontSize: 12,
  marginBottom: 4,
  color: 'var(--aa-cobalt)',
  letterSpacing: 0.4,
}

interface Props {
  // session_id to show, or null when closed
  sessionId: string | null
  onClose: () => void
}

/**
 * Reconstructed view of a Sample.session_id-linked multi-turn conversation.
 * Turns are typically spread across separate single-sample batches (each
 * turn its own submission), not one batch — GET /batches/sessions/{id}
 * queries across all of them and returns them in order.
 */
export function SessionConversationModal({ sessionId, onClose }: Props) {
  const navigate = useNavigate()
  const { data, isLoading } = useSessionConversation(sessionId)
  const turns = data ?? []

  return (
    <Modal
      open={!!sessionId}
      title={
        <span>
          多轮对话 <span className="aa-mono aa-muted" style={{ fontWeight: 400 }}>{sessionId}</span>
        </span>
      }
      onCancel={onClose}
      footer={null}
      width={720}
      destroyOnClose
    >
      {isLoading ? (
        <div style={{ textAlign: 'center', padding: 24 }}>
          <Spin />
        </div>
      ) : turns.length === 0 ? (
        <Empty description="没有找到属于这个会话的记录" />
      ) : (
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
          {turns.map((turn, index) => (
            <div
              key={`${turn.batch_id}-${turn.sample_id}`}
              style={{ border: '1px solid var(--aa-border-color, #e5e5e5)', borderRadius: 8, padding: 12 }}
            >
              <Space style={{ marginBottom: 8 }} size={8} wrap>
                <Typography.Text strong>第 {index + 1} 轮</Typography.Text>
                <StatusTag status={turn.status} />
                {turn.started_at ? (
                  <span className="aa-mono aa-muted" style={{ fontSize: 12 }}>
                    {turn.started_at}
                  </span>
                ) : null}
                <a
                  style={{ fontSize: 12 }}
                  onClick={() => navigate(`/batches/${turn.batch_id}/samples/${turn.sample_id}`)}
                >
                  查看详情
                </a>
              </Space>
              {turn.prompt !== null ? (
                <div style={{ marginBottom: turn.response !== null ? 8 : 0 }}>
                  <Typography.Text strong style={FIELD_LABEL_STYLE}>
                    PROMPT
                  </Typography.Text>
                  <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>
                    {turn.prompt}
                  </Typography.Paragraph>
                </div>
              ) : null}
              {turn.response !== null ? (
                <div style={{ marginBottom: 8 }}>
                  <Typography.Text strong style={FIELD_LABEL_STYLE}>
                    RESPONSE
                  </Typography.Text>
                  <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>
                    {turn.response ? turn.response : <span className="aa-muted">(空)</span>}
                  </Typography.Paragraph>
                </div>
              ) : null}
              {turn.prompt === null && turn.response === null ? (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  未执行(如释放设备的空操作)
                </Typography.Text>
              ) : (
                <ScreenshotStrip batchId={turn.batch_id} sampleId={turn.sample_id} />
              )}
            </div>
          ))}
        </Space>
      )}
    </Modal>
  )
}
