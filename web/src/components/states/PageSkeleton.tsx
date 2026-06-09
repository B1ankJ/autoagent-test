import { Skeleton } from 'antd'

interface PageSkeletonProps {
  /** Number of placeholder rows below the title. */
  rows?: number
  /** Show table-style skeleton (rows with extra metadata). */
  table?: boolean
}

export function PageSkeleton({ rows = 4, table }: PageSkeletonProps) {
  return (
    <div style={{ padding: '6px 0 0', display: 'flex', flexDirection: 'column', gap: 14 }}>
      <Skeleton.Input active size="small" style={{ width: 200 }} />
      {table ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {Array.from({ length: rows }).map((_, i) => (
            <div
              key={i}
              style={{
                display: 'grid',
                gridTemplateColumns: '2fr 1fr 1fr 1fr 1fr',
                gap: 12,
                padding: '12px 14px',
                background: 'var(--aa-surface)',
                border: '1px solid var(--aa-border)',
                borderRadius: 6,
              }}
            >
              <Skeleton.Input active size="small" style={{ width: '100%' }} />
              <Skeleton.Input active size="small" style={{ width: '70%' }} />
              <Skeleton.Input active size="small" style={{ width: '60%' }} />
              <Skeleton.Input active size="small" style={{ width: '80%' }} />
              <Skeleton.Input active size="small" style={{ width: '50%' }} />
            </div>
          ))}
        </div>
      ) : (
        <Skeleton active paragraph={{ rows }} />
      )}
    </div>
  )
}
