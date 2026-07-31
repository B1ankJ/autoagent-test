import { PictureOutlined, WarningOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { Button, Skeleton, Slider, Space, Tag, Typography } from 'antd'
import { useMemo, useState } from 'react'
import { listScreenshots, screenshotUrl } from '../api/screenshots'
import {
  ActionLogEntry,
  TimelineEvent,
  buildTimelineEvents,
  formatActionTarget,
} from '../utils/replayTimeline'

interface Props {
  batchId: string
  sampleId: string
  // Raw sample.metadata.action_log — validated here so the caller doesn't
  // need to know this component's expected shape.
  actionLog: unknown
}

function isActionLogEntry(value: unknown): value is ActionLogEntry {
  return (
    !!value && typeof value === 'object' && typeof (value as ActionLogEntry).t_ms === 'number'
  )
}

function findNearestScreenshot(events: TimelineEvent[], index: number) {
  for (let i = index; i >= 0; i--) {
    const event = events[i]
    if (event.kind === 'screenshot') return event.screenshot
  }
  return null
}

function markColor(event: TimelineEvent): string {
  if (event.kind === 'screenshot') return '#1677ff'
  return event.entry.ok === false ? '#ff4d4f' : '#52c41a'
}

function markTooltip(event: TimelineEvent): string {
  const seconds = (event.elapsedMs / 1000).toFixed(1)
  const what = event.kind === 'screenshot' ? event.screenshot.label : (event.entry.action ?? 'action')
  return `${what} · ${seconds}s`
}

export function SampleReplayTimeline({ batchId, sampleId, actionLog }: Props) {
  const screenshotsQ = useQuery({
    queryKey: ['screenshots', batchId, sampleId],
    queryFn: async () => listScreenshots(batchId, sampleId),
  })
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null)

  const validActionLog = Array.isArray(actionLog) ? actionLog.filter(isActionLogEntry) : []
  const events = useMemo(
    () => buildTimelineEvents(validActionLog, screenshotsQ.data ?? []),
    // validActionLog is a fresh array each render but only its *contents*
    // matter here — re-deriving it every render is cheap (a handful of
    // entries), so this intentionally skips a deep-equality dependency.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [actionLog, screenshotsQ.data],
  )

  if (screenshotsQ.isLoading) {
    return <Skeleton.Image active style={{ width: '100%', height: 320 }} />
  }

  if (screenshotsQ.isError) {
    return (
      <div
        style={{
          padding: '20px 0',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          color: 'var(--aa-amber)',
          fontSize: 13,
        }}
      >
        <WarningOutlined />
        截图加载失败
        <Button size="small" onClick={() => screenshotsQ.refetch()}>
          重试
        </Button>
      </div>
    )
  }

  if (events.length === 0) {
    return (
      <div
        style={{
          padding: '20px 0',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          color: 'var(--aa-text-muted)',
          fontSize: 13,
        }}
      >
        <PictureOutlined />
        暂无截图
      </div>
    )
  }

  const index = Math.min(selectedIndex ?? events.length - 1, events.length - 1)
  const currentEvent = events[index]
  const currentImage = findNearestScreenshot(events, index)

  const marks: Record<number, { label: React.ReactNode; style: React.CSSProperties }> = {}
  events.forEach((event, i) => {
    marks[i] = {
      style: { fontSize: 0 },
      label: (
        <span
          style={{
            display: 'inline-block',
            width: 6,
            height: 6,
            borderRadius: '50%',
            background: markColor(event),
          }}
        />
      ),
    }
  })

  return (
    <Space direction="vertical" style={{ width: '100%' }} size={12}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          background: 'var(--aa-surface-alt)',
          borderRadius: 8,
          minHeight: 320,
        }}
      >
        {currentImage ? (
          <img
            src={screenshotUrl(batchId, sampleId, currentImage.name)}
            alt={currentImage.label}
            style={{ maxWidth: '100%', maxHeight: 480, objectFit: 'contain' }}
          />
        ) : (
          <Typography.Text type="secondary">这一步没有对应截图</Typography.Text>
        )}
      </div>
      {currentEvent.kind === 'action' ? (
        <Space size={8} wrap>
          <Tag color={currentEvent.entry.ok === false ? 'error' : 'success'}>
            {currentEvent.entry.ok === false ? '失败' : '成功'}
          </Tag>
          <Typography.Text className="aa-mono">{currentEvent.entry.action ?? '-'}</Typography.Text>
          <Typography.Text type="secondary" className="aa-mono">
            {formatActionTarget(currentEvent.entry as unknown as Record<string, unknown>)}
          </Typography.Text>
          {currentEvent.entry.error ? (
            <Typography.Text type="danger">{currentEvent.entry.error}</Typography.Text>
          ) : null}
        </Space>
      ) : (
        <Typography.Text type="secondary" className="aa-mono">
          {currentEvent.screenshot.label}
        </Typography.Text>
      )}
      <Slider
        min={0}
        max={events.length - 1}
        value={index}
        onChange={(value) => setSelectedIndex(value)}
        marks={marks}
        step={1}
        tooltip={{ formatter: (value) => (value !== undefined ? markTooltip(events[value]) : '') }}
      />
    </Space>
  )
}
