import { useQuery } from '@tanstack/react-query'
import { Image, Space, Spin, Typography } from 'antd'
import { listScreenshots, screenshotPath } from '../api/screenshots'

interface Props {
  batchId: string
  sampleId: string
}

export function ScreenshotStrip({ batchId, sampleId }: Props) {
  const screenshots = useQuery({
    queryKey: ['screenshots', batchId, sampleId],
    queryFn: async () => listScreenshots(batchId, sampleId),
  })

  if (screenshots.isLoading) {
    return <Spin />
  }

  if (!screenshots.data?.length) {
    return <Typography.Text type="secondary">暂无截图</Typography.Text>
  }

  return (
    <Image.PreviewGroup>
      <Space wrap>
        {screenshots.data.map((shot) => (
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
            <Image
              key={shot.name}
              width={160}
              src={screenshotPath(batchId, sampleId, shot.name)}
              alt={shot.label}
            />
          )
        ))}
      </Space>
    </Image.PreviewGroup>
  )
}
