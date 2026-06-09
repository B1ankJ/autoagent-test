import {
  ArrowRightOutlined,
  CheckCircleFilled,
  ClockCircleOutlined,
  CloseCircleFilled,
  FileTextOutlined,
  MobileOutlined,
  PauseCircleOutlined,
  PlayCircleFilled,
  PlusOutlined,
  StopOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { Button, Card, Space, Typography } from 'antd'
import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { useBatches, useBatchStats } from '../api/batches'
import { ModeTag } from '../components/ModeTag'
import { StatusTag } from '../components/StatusTag'
import { EmptyState } from '../components/states/EmptyState'
import { PageHeader } from '../components/states/PageHeader'

interface StatCardProps {
  label: string
  value: number
  icon: ReactNode
  tone: 'cobalt' | 'amber' | 'green' | 'red' | 'muted' | 'pause'
  hint?: string
}

const TONE: Record<StatCardProps['tone'], { bg: string; fg: string }> = {
  cobalt: { bg: 'var(--aa-cobalt-soft)', fg: 'var(--aa-cobalt)' },
  amber: { bg: 'var(--aa-amber-soft)', fg: 'var(--aa-amber)' },
  green: { bg: 'rgba(34,197,94,0.14)', fg: '#16A34A' },
  red: { bg: 'rgba(239,68,68,0.14)', fg: '#DC2626' },
  muted: { bg: 'var(--aa-surface-alt)', fg: 'var(--aa-text-muted)' },
  pause: { bg: 'rgba(148,163,184,0.14)', fg: '#64748B' },
}

function StatCard({ label, value, icon, tone, hint }: StatCardProps) {
  const palette = TONE[tone]
  return (
    <div
      style={{
        flex: 1,
        minWidth: 0,
        background: 'var(--aa-surface)',
        border: '1px solid var(--aa-border)',
        borderRadius: 8,
        padding: '14px 16px',
        display: 'flex',
        alignItems: 'center',
        gap: 12,
      }}
    >
      <div
        style={{
          width: 36,
          height: 36,
          borderRadius: 8,
          background: palette.bg,
          color: palette.fg,
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 16,
          flexShrink: 0,
        }}
      >
        {icon}
      </div>
      <div style={{ minWidth: 0, display: 'flex', flexDirection: 'column', lineHeight: 1.2 }}>
        <div
          style={{
            fontSize: 11,
            letterSpacing: 0.6,
            color: 'var(--aa-text-muted)',
            textTransform: 'uppercase',
            fontFamily: 'var(--aa-mono)',
          }}
        >
          {label}
        </div>
        <div
          style={{
            fontSize: 22,
            fontWeight: 600,
            color: 'var(--aa-text)',
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          {value}
        </div>
        {hint ? (
          <div style={{ fontSize: 11, color: 'var(--aa-text-muted)', marginTop: 2 }}>{hint}</div>
        ) : null}
      </div>
    </div>
  )
}

interface QuickActionProps {
  icon: ReactNode
  title: string
  description: string
  onClick: () => void
}

function QuickAction({ icon, title, description, onClick }: QuickActionProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        all: 'unset',
        cursor: 'pointer',
        flex: 1,
        minWidth: 220,
        background: 'var(--aa-surface)',
        border: '1px solid var(--aa-border)',
        borderRadius: 8,
        padding: '14px 16px',
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        transition: 'border-color 120ms ease, transform 120ms ease, box-shadow 120ms ease',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = 'var(--aa-cobalt)'
        e.currentTarget.style.transform = 'translateY(-1px)'
        e.currentTarget.style.boxShadow = '0 6px 18px rgba(37,71,208,0.10)'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = 'var(--aa-border)'
        e.currentTarget.style.transform = 'translateY(0)'
        e.currentTarget.style.boxShadow = 'none'
      }}
    >
      <div
        style={{
          width: 38,
          height: 38,
          borderRadius: 8,
          background: 'var(--aa-cobalt-soft)',
          color: 'var(--aa-cobalt)',
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 17,
        }}
      >
        {icon}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--aa-text)' }}>{title}</div>
        <div style={{ fontSize: 12, color: 'var(--aa-text-muted)', marginTop: 2 }}>
          {description}
        </div>
      </div>
      <ArrowRightOutlined style={{ color: 'var(--aa-text-muted)' }} />
    </button>
  )
}

export function Dashboard() {
  const navigate = useNavigate()
  const { data: running } = useBatches({ limit: 6 })
  const { data: stats } = useBatchStats()
  const byStatus = {
    queued: stats?.queued ?? 0,
    running: stats?.running ?? 0,
    done: stats?.done ?? 0,
    failed: stats?.failed ?? 0,
    cancelled: stats?.cancelled ?? 0,
  }
  const total = stats?.total ?? 0
  // Live focus: queued + running batches the user might want to monitor.
  const live = (running ?? []).filter(
    (b) => b.status === 'running' || b.status === 'queued',
  )

  return (
    <div>
      <PageHeader
        eyebrow="首页"
        title="Dashboard"
        subtitle="今日运行状态与快捷入口"
      />

      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 22 }}>
        <StatCard
          label="Total"
          value={total}
          icon={<FileTextOutlined />}
          tone="muted"
        />
        <StatCard
          label="Running"
          value={byStatus.running}
          icon={<PlayCircleFilled />}
          tone="cobalt"
          hint={byStatus.running > 0 ? '正在执行' : undefined}
        />
        <StatCard
          label="Queued"
          value={byStatus.queued}
          icon={<ClockCircleOutlined />}
          tone="amber"
        />
        <StatCard
          label="Done"
          value={byStatus.done}
          icon={<CheckCircleFilled />}
          tone="green"
        />
        <StatCard
          label="Failed"
          value={byStatus.failed}
          icon={<CloseCircleFilled />}
          tone="red"
        />
        <StatCard
          label="Cancelled"
          value={byStatus.cancelled}
          icon={<StopOutlined />}
          tone="pause"
        />
      </div>

      <Typography.Title
        level={5}
        style={{ margin: '0 0 10px', fontSize: 13, color: 'var(--aa-text-muted)' }}
      >
        快捷操作
      </Typography.Title>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 22 }}>
        <QuickAction
          icon={<PlusOutlined />}
          title="新建批次"
          description="上传 JSONL/CSV 或手动配置 samples 开跑"
          onClick={() => navigate('/batches/new')}
        />
        <QuickAction
          icon={<ThunderboltOutlined />}
          title="单次测试"
          description="试一条 prompt,验证 profile 是否生效"
          onClick={() => navigate('/tests/quick')}
        />
        <QuickAction
          icon={<MobileOutlined />}
          title="设备状态"
          description="ADB 设备、Keyboard IME 一览"
          onClick={() => navigate('/devices')}
        />
      </div>

      <Card
        size="small"
        title={
          <Space size={10}>
            <PauseCircleOutlined style={{ color: 'var(--aa-cobalt)' }} />
            <span>进行中 / 排队中</span>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {live.length} 个
            </Typography.Text>
          </Space>
        }
        extra={
          <Button type="link" size="small" onClick={() => navigate('/batches')}>
            查看全部 <ArrowRightOutlined />
          </Button>
        }
        styles={{ body: { padding: live.length === 0 ? 0 : '4px 0' } }}
      >
        {live.length === 0 ? (
          <EmptyState
            compact
            title="当前没有进行中的批次"
            description="新建批次后,这里会显示运行进度。"
          />
        ) : (
          <div>
            {live.map((batch, idx) => (
              <div
                key={batch.batch_id}
                onClick={() => navigate(`/batches/${batch.batch_id}`)}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '1fr 130px 110px 110px',
                  gap: 12,
                  alignItems: 'center',
                  padding: '10px 16px',
                  borderTop: idx === 0 ? 'none' : '1px solid var(--aa-border)',
                  cursor: 'pointer',
                  transition: 'background 120ms ease',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = 'var(--aa-surface-alt)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = 'transparent'
                }}
              >
                <div style={{ minWidth: 0 }}>
                  <div
                    style={{
                      fontWeight: 600,
                      fontSize: 13,
                      color: 'var(--aa-text)',
                      whiteSpace: 'nowrap',
                      textOverflow: 'ellipsis',
                      overflow: 'hidden',
                    }}
                  >
                    {batch.name}
                  </div>
                  <div
                    className="aa-mono"
                    style={{ fontSize: 11, color: 'var(--aa-text-muted)' }}
                  >
                    {batch.batch_id.slice(0, 12)}…
                  </div>
                </div>
                <ModeTag mode={batch.mode} />
                <StatusTag status={batch.status} />
                <div
                  className="aa-mono"
                  style={{
                    fontSize: 12,
                    color: 'var(--aa-text-muted)',
                    fontVariantNumeric: 'tabular-nums',
                  }}
                >
                  {batch.done + batch.failed}/{batch.total}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}
