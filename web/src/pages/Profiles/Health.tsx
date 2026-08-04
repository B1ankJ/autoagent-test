import { Card, Col, Row, Segmented, Space, Tag, Typography } from 'antd'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { summarizeHealth, useProfileHealth } from '../../api/profileHealth'
import { EmptyState } from '../../components/states/EmptyState'
import { ErrorState } from '../../components/states/ErrorState'
import { PageHeader } from '../../components/states/PageHeader'
import type { HealthStatus, ProfileHealth } from '../../types/api'
import { formatDurationMs } from '../../utils/duration'

const STATUS_META: Record<HealthStatus, { color: string; label: string }> = {
  red: { color: '#cf1322', label: '异常' },
  yellow: { color: '#d48806', label: '警告' },
  green: { color: '#389e0d', label: '健康' },
  nodata: { color: '#8c8c8c', label: '无数据' },
}

function HealthCard({ row }: { row: ProfileHealth }) {
  const navigate = useNavigate()
  const meta = STATUS_META[row.status]
  return (
    <Card size="small" styles={{ body: { padding: 12 } }}>
      <Space style={{ marginBottom: 8 }} align="center">
        <span
          style={{
            width: 10,
            height: 10,
            borderRadius: '50%',
            background: meta.color,
            display: 'inline-block',
          }}
        />
        <a onClick={() => navigate(`/profiles/${row.name}`)} style={{ fontWeight: 600 }}>
          {row.name}
        </a>
        <Tag>{row.platform}</Tag>
      </Space>
      <div style={{ fontSize: 13, lineHeight: 1.9 }}>
        <div>
          成功率 {row.success_rate === null ? '—' : `${Math.round(row.success_rate * 100)}%`}{' '}
          <Typography.Text type="secondary">({row.total_runs} 次)</Typography.Text>
        </div>
        <div>耗时 {row.avg_duration_ms === null ? '—' : formatDurationMs(row.avg_duration_ms)}</div>
        <div>
          <a
            onClick={() =>
              navigate(`/system/anomalies?target_profile=${encodeURIComponent(row.name)}`)
            }
          >
            异常 {row.unacked_anomalies}
          </a>
        </div>
        <div>
          设备 {row.devices_total === null ? '—' : `${row.devices_online}/${row.devices_total}`}
        </div>
      </div>
    </Card>
  )
}

export function Health() {
  const { data, isLoading, isError, refetch } = useProfileHealth()
  const [unhealthyOnly, setUnhealthyOnly] = useState(false)

  // The backend already returns profiles worst-first (see profile_health.py's
  // _SEVERITY sort) — render that order as-is rather than re-sorting here, so
  // the ordering has a single source of truth and can't drift.
  const rows = useMemo(() => {
    const all = data ?? []
    return unhealthyOnly ? all.filter((r) => r.status === 'red' || r.status === 'yellow') : all
  }, [data, unhealthyOnly])

  const summary = useMemo(() => summarizeHealth(data ?? []), [data])

  if (isError) return <ErrorState title="加载失败" onRetry={() => refetch()} />

  return (
    <div>
      <PageHeader title="Profile 健康" subtitle="近 7 天每个配置档的健康快照" />
      <Space style={{ marginBottom: 12 }} wrap>
        <Typography.Text type="secondary">
          {summary.green} 健康 · {summary.yellow} 警告 · {summary.red} 异常 · {summary.nodata}{' '}
          无数据
        </Typography.Text>
        <Segmented
          value={unhealthyOnly ? 'unhealthy' : 'all'}
          onChange={(v) => setUnhealthyOnly(v === 'unhealthy')}
          options={[
            { value: 'all', label: '全部' },
            { value: 'unhealthy', label: '只看非健康' },
          ]}
        />
      </Space>
      {!isLoading && rows.length === 0 ? (
        <EmptyState title="没有配置档" description="先创建配置档并运行批次后再来看健康度。" />
      ) : (
        <Row gutter={[12, 12]}>
          {rows.map((r) => (
            <Col key={r.name} xs={24} sm={12} md={8} lg={6}>
              <HealthCard row={r} />
            </Col>
          ))}
        </Row>
      )}
    </div>
  )
}
