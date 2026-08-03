import { Button, Collapse, Space, Tag, Typography } from 'antd'
import { groupFailuresByError } from '../utils/failureClustering'
import type { Sample } from '../types/api'

interface Props {
  samples: Sample[]
  activeClusterId: string | null
  onSelectCluster: (id: string | null) => void
}

const MIN_FAILURES_TO_SHOW = 2

export function FailureClusterPanel({ samples, activeClusterId, onSelectCluster }: Props) {
  const clusters = groupFailuresByError(samples)
  const failedCount = clusters.reduce((sum, c) => sum + c.count, 0)

  if (failedCount < MIN_FAILURES_TO_SHOW) return null

  return (
    <Collapse
      style={{ marginBottom: 12 }}
      items={[
        {
          key: 'clusters',
          label: `错误分组 (${clusters.length})`,
          children: (
            <Space direction="vertical" style={{ width: '100%' }} size={8}>
              {clusters.map((cluster) => {
                const isActive = activeClusterId === cluster.pattern
                return (
                  <div
                    key={cluster.pattern}
                    style={{
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: 10,
                      padding: 8,
                      border: '1px solid var(--aa-border, #e5e5e5)',
                      borderRadius: 6,
                      background: isActive ? 'var(--aa-surface-alt)' : undefined,
                    }}
                  >
                    <Tag color="blue">{cluster.count}</Tag>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <Typography.Text className="aa-mono" strong>
                        {cluster.pattern}
                      </Typography.Text>
                      <Typography.Paragraph
                        type="secondary"
                        style={{ marginBottom: 0, fontSize: 12 }}
                        ellipsis={{ rows: 2, expandable: true, symbol: '展开' }}
                      >
                        {cluster.example}
                      </Typography.Paragraph>
                    </div>
                    <Button
                      size="small"
                      type={isActive ? 'primary' : 'default'}
                      onClick={() => onSelectCluster(isActive ? null : cluster.pattern)}
                    >
                      {isActive ? '取消筛选' : '筛选'}
                    </Button>
                  </div>
                )
              })}
            </Space>
          ),
        },
      ]}
    />
  )
}
