import { InboxOutlined } from '@ant-design/icons'
import { Typography } from 'antd'
import type { ReactNode } from 'react'

interface EmptyStateProps {
  title: ReactNode
  description?: ReactNode
  /** Action element (e.g. <Button>). */
  action?: ReactNode
  icon?: ReactNode
  /** When true, render in a compact inline form for table empty slots. */
  compact?: boolean
}

export function EmptyState({
  title,
  description,
  action,
  icon = <InboxOutlined />,
  compact,
}: EmptyStateProps) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: compact ? 6 : 12,
        padding: compact ? '24px 16px' : '52px 24px',
        textAlign: 'center',
      }}
    >
      <div
        style={{
          width: compact ? 36 : 56,
          height: compact ? 36 : 56,
          borderRadius: '50%',
          background: 'var(--aa-cobalt-soft)',
          color: 'var(--aa-cobalt)',
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: compact ? 16 : 22,
          marginBottom: compact ? 0 : 4,
        }}
      >
        {icon}
      </div>
      <Typography.Text
        strong
        style={{
          fontSize: compact ? 13 : 15,
          color: 'var(--aa-text)',
        }}
      >
        {title}
      </Typography.Text>
      {description ? (
        <Typography.Text type="secondary" style={{ maxWidth: 360, fontSize: 12 }}>
          {description}
        </Typography.Text>
      ) : null}
      {action ? <div style={{ marginTop: compact ? 4 : 8 }}>{action}</div> : null}
    </div>
  )
}
