import { EyeInvisibleOutlined, PictureOutlined, WarningOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { Button, Image, Skeleton, Typography } from 'antd'
import { listScreenshots, screenshotUrl } from '../api/screenshots'

interface Props {
  batchId: string
  sampleId: string
}

function formatScreenshotLabel(label: string): string {
  const patterns: Array<[RegExp, (match: RegExpExecArray) => string]> = [
    [/^before_input_(\d+)$/, (match) => `输入前 ${match[1]}`],
    [/^after_input_(\d+)$/, (match) => `输入后 ${match[1]}`],
    [/^after_send_(\d+)$/, (match) => `发送后 ${match[1]}`],
    [/^after_result_(\d+)$/, (match) => `结果后 ${match[1]}`],
    [/^done_(\d+)$/, (match) => `完成后 ${match[1]}`],
  ]
  for (const [pattern, formatter] of patterns) {
    const match = pattern.exec(label)
    if (match) {
      return formatter(match)
    }
  }
  return label
}

const THUMB_W = 168
const THUMB_H = 240
// 2x the display width for crisp thumbnails on retina; the server caps at 720.
const THUMB_FETCH_W = THUMB_W * 2

export function ScreenshotStrip({ batchId, sampleId }: Props) {
  const screenshots = useQuery({
    queryKey: ['screenshots', batchId, sampleId],
    queryFn: async () => listScreenshots(batchId, sampleId),
  })

  if (screenshots.isLoading) {
    return (
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        {[0, 1, 2].map((i) => (
          <Skeleton.Image active key={i} style={{ width: THUMB_W, height: THUMB_H }} />
        ))}
      </div>
    )
  }

  if (screenshots.isError) {
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
        <Button size="small" onClick={() => screenshots.refetch()}>
          重试
        </Button>
      </div>
    )
  }

  if (!screenshots.data?.length) {
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

  return (
    <Image.PreviewGroup>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 14 }}>
        {screenshots.data.map((shot, index) => {
          const stepNo = String(index + 1).padStart(2, '0')
          if (shot.is_sensitive) {
            return (
              <div
                key={shot.name}
                style={{
                  width: THUMB_W,
                  height: THUMB_H,
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 6,
                  border: '1px dashed var(--aa-border-strong)',
                  borderRadius: 8,
                  background: 'var(--aa-surface-alt)',
                  color: 'var(--aa-text-muted)',
                  fontSize: 12,
                }}
              >
                <EyeInvisibleOutlined style={{ fontSize: 20 }} />
                敏感截图已隐藏
              </div>
            )
          }

          const thumbUrl = screenshotUrl(batchId, sampleId, shot.name, THUMB_FETCH_W)
          const fullUrl = screenshotUrl(batchId, sampleId, shot.name)
          const pretty = formatScreenshotLabel(shot.label)

          return (
            <figure
              key={shot.name}
              style={{
                margin: 0,
                width: THUMB_W,
                display: 'flex',
                flexDirection: 'column',
                gap: 6,
              }}
            >
              <div
                style={{
                  position: 'relative',
                  width: THUMB_W,
                  height: THUMB_H,
                  borderRadius: 8,
                  overflow: 'hidden',
                  background: 'var(--aa-surface-alt)',
                  border: '1px solid var(--aa-border)',
                  cursor: 'zoom-in',
                  transition: 'border-color 120ms ease, transform 120ms ease',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = 'var(--aa-cobalt)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = 'var(--aa-border)'
                }}
              >
                <Image
                  src={thumbUrl}
                  alt={shot.label}
                  width={THUMB_W}
                  height={THUMB_H}
                  loading="lazy"
                  style={{ objectFit: 'cover' }}
                  placeholder={
                    <Skeleton.Image active style={{ width: THUMB_W, height: THUMB_H }} />
                  }
                  preview={{
                    src: fullUrl,
                    mask: (
                      <span style={{ fontSize: 12 }}>
                        步骤 {stepNo} · {pretty}
                      </span>
                    ),
                  }}
                />
                <span
                  style={{
                    position: 'absolute',
                    top: 6,
                    left: 6,
                    padding: '1px 6px',
                    fontFamily: 'var(--aa-mono)',
                    fontSize: 10,
                    color: '#fff',
                    background: 'rgba(11,13,18,0.7)',
                    borderRadius: 4,
                    letterSpacing: 0.4,
                  }}
                >
                  {stepNo}
                </span>
              </div>
              <figcaption
                style={{ textAlign: 'left', display: 'flex', flexDirection: 'column', gap: 1 }}
              >
                <Typography.Text
                  style={{ fontSize: 12, color: 'var(--aa-text)' }}
                  ellipsis={{ tooltip: `${pretty} (${shot.label})` }}
                >
                  {pretty}
                </Typography.Text>
                <Typography.Text
                  className="aa-mono"
                  style={{ fontSize: 10.5, color: 'var(--aa-text-muted)' }}
                  ellipsis={{ tooltip: shot.label }}
                >
                  {shot.label}
                </Typography.Text>
              </figcaption>
            </figure>
          )
        })}
      </div>
    </Image.PreviewGroup>
  )
}
