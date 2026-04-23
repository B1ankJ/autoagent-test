import { Alert, Button, Input, Modal, Space, Typography } from 'antd'
import { useState } from 'react'
import { useRunSync } from '../../api/tests'
import { ExecutionMode } from '../../types/api'

interface Props {
  open: boolean
  profileName: string
  mode: ExecutionMode
  onClose: () => void
}

export function ConnectivityTestModal({ open, profileName, mode, onClose }: Props) {
  const [prompt, setPrompt] = useState('hello')
  const run = useRunSync()
  const timeoutSec = mode === 'api' ? 60 : 180
  const requestTimeoutMs = mode === 'api' ? 65_000 : 215_000

  const onSend = async () => {
    await run.mutateAsync({
      sample: {
        id: `conn-${Date.now()}`,
        prompts: [prompt],
        mode,
        target_profile: profileName,
        timeout_sec: timeoutSec,
      },
      timeoutMs: requestTimeoutMs,
    })
  }

  return (
    <Modal
      title={`连通性测试: ${profileName}`}
      open={open}
      onCancel={onClose}
      footer={null}
      destroyOnHidden
    >
      <Space direction="vertical" style={{ width: '100%' }}>
        <Input
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          placeholder="测试 prompt"
        />
        <Button type="primary" onClick={onSend} loading={run.isPending} block>
          发送
        </Button>
        {run.data ? (
          run.data.status === 'done' ? (
            <Alert
              type="success"
              message="成功"
              description={<Typography.Paragraph>{run.data.responses[0]}</Typography.Paragraph>}
            />
          ) : (
            <Alert type="error" message="失败" description={run.data.error ?? '未知错误'} />
          )
        ) : null}
        {run.error ? (
          <Alert type="error" message="请求错误" description={(run.error as Error).message} />
        ) : null}
      </Space>
    </Modal>
  )
}
