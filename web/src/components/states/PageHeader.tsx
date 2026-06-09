import { Space, Typography } from 'antd'
import type { ReactNode } from 'react'

interface PageHeaderProps {
  title: ReactNode
  subtitle?: ReactNode
  /** Right-aligned action area (buttons, search). */
  extra?: ReactNode
  /** Small upper-line tag (breadcrumb-ish). */
  eyebrow?: ReactNode
}

export function PageHeader({ title, subtitle, extra, eyebrow }: PageHeaderProps) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-end',
        justifyContent: 'space-between',
        gap: 16,
        marginBottom: 18,
        paddingBottom: 14,
        borderBottom: '1px solid var(--aa-border)',
      }}
    >
      <Space direction="vertical" size={2}>
        {eyebrow ? (
          <Typography.Text
            style={{
              fontSize: 11,
              letterSpacing: 1.4,
              textTransform: 'uppercase',
              color: 'var(--aa-text-muted)',
              fontFamily: 'var(--aa-mono)',
            }}
          >
            {eyebrow}
          </Typography.Text>
        ) : null}
        <Typography.Title level={3} style={{ margin: 0, fontWeight: 600, fontSize: 20 }}>
          {title}
        </Typography.Title>
        {subtitle ? (
          <Typography.Text type="secondary" style={{ fontSize: 13 }}>
            {subtitle}
          </Typography.Text>
        ) : null}
      </Space>
      {extra ? <Space size={8}>{extra}</Space> : null}
    </div>
  )
}
