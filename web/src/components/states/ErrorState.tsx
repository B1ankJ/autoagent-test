import { ExclamationCircleFilled } from '@ant-design/icons'
import { Button, Typography } from 'antd'
import type { ReactNode } from 'react'

interface ErrorStateProps {
  title?: ReactNode
  description?: ReactNode
  /** If provided, renders a Retry button that calls this. */
  onRetry?: () => void
  retryLabel?: string
  /** Raw error to render as muted mono detail (e.g. error.message). */
  detail?: string
}

export function ErrorState({
  title = '加载失败',
  description = '请检查网络或稍后再试。',
  onRetry,
  retryLabel = '重试',
  detail,
}: ErrorStateProps) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 10,
        padding: '52px 24px',
        textAlign: 'center',
      }}
    >
      <div
        style={{
          width: 48,
          height: 48,
          borderRadius: '50%',
          background: 'var(--aa-amber-soft)',
          color: 'var(--aa-amber)',
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 22,
        }}
      >
        <ExclamationCircleFilled />
      </div>
      <Typography.Text strong style={{ fontSize: 15 }}>
        {title}
      </Typography.Text>
      <Typography.Text type="secondary" style={{ maxWidth: 420, fontSize: 12 }}>
        {description}
      </Typography.Text>
      {detail ? (
        <div
          className="aa-mono"
          style={{
            maxWidth: 520,
            padding: '8px 12px',
            borderRadius: 6,
            background: 'var(--aa-surface-alt)',
            color: 'var(--aa-text-muted)',
            fontSize: 11,
            wordBreak: 'break-word',
            textAlign: 'left',
          }}
        >
          {detail}
        </div>
      ) : null}
      {onRetry ? (
        <Button type="primary" onClick={onRetry} style={{ marginTop: 4 }}>
          {retryLabel}
        </Button>
      ) : null}
    </div>
  )
}
