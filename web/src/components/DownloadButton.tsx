import { DownloadOutlined } from '@ant-design/icons'
import { App, Button } from 'antd'
import { useState } from 'react'
import { client } from '../api/client'
import { parseContentDisposition, triggerDownload } from '../utils/download'

interface Props {
  batchId: string
}

export function DownloadButton({ batchId }: Props) {
  const [loading, setLoading] = useState(false)
  const { message } = App.useApp()

  const onClick = async () => {
    setLoading(true)
    try {
      const response = await client.get(`/batches/${batchId}/results`, { responseType: 'blob' })
      const filename =
        parseContentDisposition(response.headers['content-disposition']) ?? `${batchId}.zip`
      triggerDownload(response.data as Blob, filename)
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Button
      icon={<DownloadOutlined />}
      loading={loading}
      onClick={onClick}
      title="zip 包含 JSONL 结果 + logs 目录（截图 / XML / action_log）"
    >
      下载结果
    </Button>
  )
}
