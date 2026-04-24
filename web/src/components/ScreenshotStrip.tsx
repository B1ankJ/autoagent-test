import { useQueries, useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { Image, Space, Spin, Typography } from 'antd'
import { fetchScreenshotBlobUrl, listScreenshots } from '../api/screenshots'

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

export function ScreenshotStrip({ batchId, sampleId }: Props) {
  const screenshots = useQuery({
    queryKey: ['screenshots', batchId, sampleId],
    queryFn: async () => listScreenshots(batchId, sampleId),
  })
  const screenshotUrls = useQueries({
    queries: (screenshots.data ?? [])
      .filter((shot) => !shot.is_sensitive)
      .map((shot) => ({
        queryKey: ['screenshot-blob', batchId, sampleId, shot.name],
        queryFn: async () => fetchScreenshotBlobUrl(batchId, sampleId, shot.name),
        staleTime: Infinity,
      })),
  })

  useEffect(() => {
    return () => {
      const revoke = URL.revokeObjectURL
      if (typeof revoke !== 'function') {
        return
      }
      screenshotUrls.forEach((query) => {
        if (typeof query.data === 'string') {
          revoke(query.data)
        }
      })
    }
  }, [screenshotUrls])

  if (screenshots.isLoading) {
    return <Spin />
  }

  if (!screenshots.data?.length) {
    return <Typography.Text type="secondary">暂无截图</Typography.Text>
  }

  return (
    <Image.PreviewGroup>
      <Space wrap>
        {screenshots.data.map((shot, index) =>
          shot.is_sensitive ? (
            <div
              key={shot.name}
              style={{
                width: 160,
                height: 96,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                border: '1px dashed #d9d9d9',
                borderRadius: 8,
              }}
            >
              <Typography.Text type="secondary">敏感截图已隐藏</Typography.Text>
            </div>
          ) : (
            <Space
              key={shot.name}
              direction="vertical"
              size={4}
              style={{ alignItems: 'center', width: 160 }}
            >
              <Image width={160} src={screenshotUrls[index]?.data} alt={shot.label} />
              <Typography.Text
                style={{ width: '100%', textAlign: 'center' }}
                ellipsis={{ tooltip: `${formatScreenshotLabel(shot.label)} (${shot.label})` }}
              >
                {formatScreenshotLabel(shot.label)}
              </Typography.Text>
            </Space>
          ),
        )}
      </Space>
    </Image.PreviewGroup>
  )
}
