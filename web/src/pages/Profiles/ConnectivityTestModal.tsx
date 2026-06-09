import { Alert, Button, Input, Modal, Space, Typography } from 'antd'
import { useState } from 'react'
import { useRunSync } from '../../api/tests'
import { ResponseComparison } from '../../components/ResponseComparison'
import { ExecutionMode } from '../../types/api'
import { hasLLMExtractionData } from '../../utils/llmExtraction'

export interface ConnectivitySummary {
  ok: boolean
  prompt: string
  durationMs: number | null
  error?: string | null
  ts: number
}

interface Props {
  open: boolean
  profileName: string
  mode: ExecutionMode
  onClose: () => void
  /** Reported every time a run resolves (success or failure). */
  onResult?: (summary: ConnectivitySummary) => void
}

export function ConnectivityTestModal({ open, profileName, mode, onClose, onResult }: Props) {
  const [prompt, setPrompt] = useState('hello')
  const run = useRunSync()
  const timeoutSec = mode === 'api' ? 60 : 180
  const requestTimeoutMs = mode === 'api' ? 65_000 : 215_000

  const onSend = async () => {
    try {
      const result = await run.mutateAsync({
        sample: {
          id: `conn-${Date.now()}`,
          prompts: [prompt],
          mode,
          target_profile: profileName,
          timeout_sec: timeoutSec,
        },
        timeoutMs: requestTimeoutMs,
      })
      onResult?.({
        ok: result.status === 'done',
        prompt,
        durationMs: result.duration_ms ?? null,
        error: result.status === 'done' ? null : (result.error ?? '未知错误'),
        ts: Date.now(),
      })
    } catch (error) {
      onResult?.({
        ok: false,
        prompt,
        durationMs: null,
        error: (error as Error).message,
        ts: Date.now(),
      })
    }
  }
  const llmEnabled = hasLLMExtractionData(run.data?.llm_responses, run.data?.llm_errors)

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
            <Space direction="vertical" style={{ width: '100%' }} size="middle">
              <Alert type="success" message="成功" />
              <Typography.Text type="secondary">
                duration: {run.data.duration_ms ?? '-'} ms
              </Typography.Text>
              <ResponseComparison
                ruleResponse={run.data.responses[0]}
                llmResponse={run.data.llm_responses?.[0]}
                llmError={run.data.llm_errors?.[0]}
                llmEnabled={llmEnabled}
              />
            </Space>
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
