import {
  ArrowLeftOutlined,
  BellFilled,
  BellOutlined,
  ExperimentOutlined,
  HistoryOutlined,
  RedoOutlined,
} from '@ant-design/icons'
import {
  App,
  Button,
  Card,
  Descriptions,
  Dropdown,
  Input,
  Popconfirm,
  Progress,
  Segmented,
  Space,
  Table,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { cloneElement, useMemo, useState } from 'react'
import type { ReactElement } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import {
  statusIsTerminal,
  useBatchStream,
  useCancelBatch,
  useReplayBatch,
  useRerunBatch,
} from '../../api/batches'
import { DownloadButton } from '../../components/DownloadButton'
import {
  getNotificationPermission,
  requestNotificationPermission,
  useBatchDoneNotification,
  type NotificationPermissionState,
} from '../../hooks/useBatchDoneNotification'
import { RunningThumbGrid } from '../../components/RunningThumbGrid'
import { StatusTag } from '../../components/StatusTag'
import { EmptyState } from '../../components/states/EmptyState'
import { ErrorState } from '../../components/states/ErrorState'
import { PageHeader } from '../../components/states/PageHeader'
import { PageSkeleton } from '../../components/states/PageSkeleton'
import { useResizableColumns } from '../../hooks/useResizableColumns'
import { Sample } from '../../types/api'

type SampleFilter = 'all' | 'running' | 'done' | 'failed' | 'cancelled' | 'queued'

function formatEta(ms: number): string {
  const sec = Math.max(1, Math.round(ms / 1000))
  if (sec < 60) return `${sec} 秒`
  const min = Math.round(sec / 60)
  if (min < 60) return `${min} 分钟`
  const hr = Math.floor(min / 60)
  const remMin = min % 60
  return remMin > 0 ? `${hr} 小时 ${remMin} 分钟` : `${hr} 小时`
}

export function BatchDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const { data, isLoading, isError, error, refetch } = useBatchStream(id)
  const cancel = useCancelBatch()
  const rerun = useRerunBatch()
  const replay = useReplayBatch()
  const { message } = App.useApp()
  const [filter, setFilter] = useState<SampleFilter>('all')
  const [search, setSearch] = useState('')
  const [notifyPerm, setNotifyPerm] = useState<NotificationPermissionState>(
    () => getNotificationPermission(),
  )

  useBatchDoneNotification({
    batchId: data?.batch_id,
    name: data?.name,
    status: data?.status,
    done: data?.done ?? 0,
    failed: data?.failed ?? 0,
  })

  const allSamples = useMemo(() => data?.samples ?? [], [data?.samples])
  // Per-status counts for the segmented filter labels — computed off the full
  // sample list, not the filtered view, so the badges stay stable as the user
  // toggles between statuses.
  const counts = useMemo(() => {
    const c = { all: allSamples.length, running: 0, done: 0, failed: 0, cancelled: 0, queued: 0 }
    for (const s of allSamples) {
      if (s.status && s.status in c) c[s.status as keyof typeof c]++
    }
    return c
  }, [allSamples])
  const filteredSamples = useMemo(() => {
    const q = search.trim().toLowerCase()
    return allSamples.filter((s) => {
      if (filter !== 'all' && s.status !== filter) return false
      if (!q) return true
      if (s.id.toLowerCase().includes(q)) return true
      if (s.error && s.error.toLowerCase().includes(q)) return true
      if ((s.prompts_sent ?? s.prompts)?.some((p) => p.toLowerCase().includes(q))) return true
      if (s.responses?.some((r) => r.toLowerCase().includes(q))) return true
      if (s.llm_responses?.some((r) => r?.toLowerCase().includes(q))) return true
      return false
    })
  }, [allSamples, filter, search])

  const sampleColumns: ColumnsType<Sample> = [
    {
      title: 'ID',
      dataIndex: 'id',
      render: (value: string) => (
        <a
          className="aa-mono"
          onClick={() =>
            navigate(`/batches/${data?.batch_id}/samples/${encodeURIComponent(value)}`)
          }
        >
          {value}
        </a>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (status: Sample['status']) => (status ? <StatusTag status={status} /> : '-'),
    },
    {
      title: '耗时 (ms)',
      dataIndex: 'duration_ms',
      width: 120,
      render: (value?: number) => (
        <span className="aa-mono aa-muted" style={{ fontVariantNumeric: 'tabular-nums' }}>
          {value ?? '-'}
        </span>
      ),
    },
    {
      title: '错误',
      dataIndex: 'error',
      render: (value?: string) =>
        value ? (
          <span className="aa-mono" title={value} style={{ color: 'var(--aa-amber)' }}>
            {value.slice(0, 80)}
          </span>
        ) : (
          <span className="aa-muted">-</span>
        ),
    },
  ]
  const {
    columns: resizableSampleColumns,
    components: sampleTableComponents,
    scroll: sampleTableScroll,
  } = useResizableColumns(sampleColumns, 'autoagent_batch_samples_col_widths')

  if (isError) {
    return (
      <div>
        <PageHeader eyebrow="任务 / 批次" title="加载失败" />
        <ErrorState
          title="批次加载失败"
          description="可能是网络问题或批次已被删除。"
          detail={(error as Error)?.message}
          onRetry={() => refetch()}
        />
      </div>
    )
  }

  if (isLoading || !data) {
    return (
      <div>
        <PageHeader eyebrow="任务 / 批次" title="加载中…" />
        <PageSkeleton rows={6} />
      </div>
    )
  }

  const total = data.total
  const completed = data.done + data.failed
  const canCancel = data.status === 'running' || data.status === 'queued'
  const percent = total ? Math.round((completed / total) * 100) : 0
  // Naive ETA: remaining samples / concurrency × average per-sample duration.
  // The avg only stabilizes after a few samples finish, so suppress the
  // estimate while it's missing or while the batch is queued.
  const eta = (() => {
    if (statusIsTerminal(data.status)) return null
    const remaining = total - completed
    if (remaining <= 0) return null
    const avg = data.avg_duration_ms
    if (!avg || avg <= 0) return null
    const concurrency = Math.max(1, data.concurrency || 1)
    return Math.round((remaining / concurrency) * avg)
  })()

  const onCancel = async () => {
    try {
      await cancel.mutateAsync(data.batch_id)
      message.success('已请求取消')
    } catch (error) {
      message.error((error as Error).message)
    }
  }

  const onRerun = async (which: 'failed' | 'all') => {
    try {
      const result = await rerun.mutateAsync({ id: data.batch_id, status: which })
      message.success('已创建重跑批次')
      navigate(`/batches/${result.batch_id}`)
    } catch (error) {
      message.error((error as Error).message)
    }
  }

  const onReplay = async () => {
    try {
      const result = await replay.mutateAsync(data.batch_id)
      message.success('已创建重放批次(配置与原批次完全一致)')
      navigate(`/batches/${result.batch_id}`)
    } catch (error) {
      message.error((error as Error).message)
    }
  }

  const onToggleNotify = async () => {
    if (notifyPerm === 'unsupported') {
      message.warning('当前浏览器不支持通知')
      return
    }
    if (notifyPerm === 'denied') {
      message.warning('通知权限已被拒绝,请到浏览器设置开启')
      return
    }
    const result = await requestNotificationPermission()
    setNotifyPerm(result)
    if (result === 'granted') {
      message.success('已开启通知,批次完成时会提醒')
    } else if (result === 'denied') {
      message.warning('已拒绝通知权限')
    }
  }
  const notifyTitle =
    notifyPerm === 'granted'
      ? '通知已启用,批次完成时会提醒'
      : notifyPerm === 'denied'
        ? '通知权限已被拒绝'
        : notifyPerm === 'unsupported'
          ? '当前浏览器不支持通知'
          : '开启批次完成通知'

  return (
    <div>
      <PageHeader
        eyebrow={
          <Space size={6}>
            <a
              onClick={() => {
                // Filters/pagination/search on Batches List live in the URL
                // query string — navigating here always used to hard-jump to
                // the bare "/batches" path, silently discarding all of that.
                // Prefer real browser-history back (preserves the querystring
                // the user actually had) and only fall back to a plain list
                // navigation when there's nothing in this SPA session to go
                // back to (e.g. a bookmarked/deep link straight into this page).
                if (location.key === 'default') {
                  navigate('/batches')
                } else {
                  navigate(-1)
                }
              }}
              style={{ color: 'var(--aa-text-muted)' }}
            >
              <ArrowLeftOutlined /> 批次
            </a>
            <span>/ 详情</span>
          </Space>
        }
        title={data.name}
        subtitle={
          <Typography.Text
            className="aa-mono aa-muted"
            style={{ fontSize: 12 }}
            copyable={{ text: data.batch_id, tooltips: ['复制', '已复制'] }}
          >
            {data.batch_id}
          </Typography.Text>
        }
        extra={
          <>
            {!statusIsTerminal(data.status) ? (
              <Button
                title={notifyTitle}
                icon={notifyPerm === 'granted' ? <BellFilled /> : <BellOutlined />}
                type={notifyPerm === 'granted' ? 'primary' : 'default'}
                onClick={onToggleNotify}
              >
                {notifyPerm === 'granted' ? '通知已开' : '通知'}
              </Button>
            ) : null}
            {statusIsTerminal(data.status) ? (
              <Dropdown.Button
                loading={rerun.isPending || replay.isPending}
                icon={<RedoOutlined />}
                onClick={() => onRerun('failed')}
                // Only the primary "重跑失败" action depends on there being
                // failed samples — 重跑全部/完整重放 don't. A top-level
                // `disabled` would grey out the caret too, making the menu
                // unreachable whenever failed === 0 (the common case for a
                // fully successful batch). buttonsRender scopes disabled to
                // just the left button.
                buttonsRender={([leftButton, rightButton]) => [
                  cloneElement(leftButton as ReactElement, { disabled: data.failed === 0 }),
                  rightButton,
                ]}
                menu={{
                  items: [
                    {
                      key: 'failed',
                      label: `重跑失败 (${data.failed})`,
                      disabled: data.failed === 0,
                      onClick: () => onRerun('failed'),
                    },
                    {
                      key: 'all',
                      label: `重跑全部 (${data.total})`,
                      onClick: () => onRerun('all'),
                    },
                    { type: 'divider' as const },
                    {
                      key: 'replay',
                      icon: <HistoryOutlined />,
                      label: '完整重放(与原批次配置完全一致)',
                      onClick: onReplay,
                    },
                  ],
                }}
              >
                重跑失败 {data.failed > 0 ? `(${data.failed})` : ''}
              </Dropdown.Button>
            ) : null}
            <Popconfirm
              title="取消此批次?"
              description="取消后未完成 sample 将中止,已完成结果保留。"
              onConfirm={onCancel}
              disabled={!canCancel}
            >
              <Button danger disabled={!canCancel} loading={cancel.isPending}>
                {cancel.isPending ? '取消中…' : '取消'}
              </Button>
            </Popconfirm>
            <DownloadButton batchId={data.batch_id} />
          </>
        }
      />

      <Card size="small" style={{ marginBottom: 16 }}>
        <Descriptions column={3} size="small" colon={false} labelStyle={{ color: 'var(--aa-text-muted)' }}>
          <Descriptions.Item label="状态">
            <StatusTag status={data.status} />
          </Descriptions.Item>
          <Descriptions.Item label="模式">{data.mode}</Descriptions.Item>
          <Descriptions.Item label="并发">{data.concurrency}</Descriptions.Item>
          <Descriptions.Item label="开始时间">
            <span className="aa-mono">{data.started_at ?? '-'}</span>
          </Descriptions.Item>
          <Descriptions.Item label="结束时间">
            <span className="aa-mono">{data.ended_at ?? '-'}</span>
          </Descriptions.Item>
          <Descriptions.Item label="进度">
            <span className="aa-mono" style={{ fontVariantNumeric: 'tabular-nums' }}>
              {completed} / {total}
            </span>
          </Descriptions.Item>
        </Descriptions>
        <Progress
          percent={percent}
          status={statusIsTerminal(data.status) ? 'normal' : 'active'}
          style={{ marginTop: 12 }}
        />
        <Space size={10}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            done {data.done} · failed {data.failed}
          </Typography.Text>
          {eta !== null ? (
            <Typography.Text style={{ fontSize: 12, color: 'var(--aa-cobalt)' }}>
              · 预计还需 {formatEta(eta)}
            </Typography.Text>
          ) : null}
        </Space>
      </Card>

      {counts.running > 0 ? (
        <Card
          size="small"
          title="运行中预览"
          style={{ marginBottom: 16 }}
          styles={{ body: { padding: '0 12px' } }}
        >
          <RunningThumbGrid batchId={data.batch_id} samples={allSamples} />
        </Card>
      ) : null}

      {allSamples.length === 0 ? (
        <EmptyState
          icon={<ExperimentOutlined />}
          title="还没有 sample 结果"
          description="批次刚启动时这里是空的;sample 完成后会立即显示。"
        />
      ) : (
        <>
          <Space wrap style={{ marginBottom: 12 }}>
            <Segmented<SampleFilter>
              value={filter}
              onChange={setFilter}
              options={[
                { label: `全部 (${counts.all})`, value: 'all' },
                { label: `running (${counts.running})`, value: 'running' },
                { label: `done (${counts.done})`, value: 'done' },
                { label: `failed (${counts.failed})`, value: 'failed' },
                { label: `queued (${counts.queued})`, value: 'queued' },
                { label: `cancelled (${counts.cancelled})`, value: 'cancelled' },
              ]}
            />
            <Input.Search
              placeholder="搜索 sample id / error / prompt / response"
              allowClear
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{ width: 280 }}
            />
            {(filter !== 'all' || search) && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                匹配 {filteredSamples.length} / {allSamples.length}
              </Typography.Text>
            )}
          </Space>
          {filteredSamples.length === 0 ? (
            <EmptyState
              compact
              icon={<ExperimentOutlined />}
              title="没有匹配的 sample"
              description="换个筛选条件,或清空搜索。"
            />
          ) : (
            <Table<Sample>
              rowKey="id"
              size="small"
              dataSource={filteredSamples}
              columns={resizableSampleColumns}
              components={sampleTableComponents}
              scroll={sampleTableScroll}
              tableLayout="fixed"
              pagination={{ pageSize: 50, showSizeChanger: true }}
            />
          )}
        </>
      )}
    </div>
  )
}
