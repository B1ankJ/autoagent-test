import {
  App,
  Button,
  Card,
  Collapse,
  Form,
  Input,
  Radio,
  Select,
  Space,
  Spin,
  Typography,
} from 'antd'
import { useState } from 'react'
import { client } from '../../api/client'
import { ResponseComparison } from '../../components/ResponseComparison'
import { useProfiles } from '../../api/profiles'
import { useAsyncResult, useRunAsync } from '../../api/tests'
import { ExecutionMode, SingleTestSyncResponse } from '../../types/api'
import { hasLLMExtractionData } from '../../utils/llmExtraction'

interface FormValues {
  id?: string
  mode: ExecutionMode
  target_profile: string
  prompts: string
  kind: 'sync' | 'async'
}

export function TestsQuick() {
  const [form] = Form.useForm<FormValues>()
  const profiles = useProfiles()
  const runAsync = useRunAsync()
  const [asyncTaskId, setAsyncTaskId] = useState<string | undefined>()
  const asyncResult = useAsyncResult(asyncTaskId)
  const { message } = App.useApp()
  const [lastSyncResult, setLastSyncResult] = useState<SingleTestSyncResponse | null>(null)
  const mode = Form.useWatch('mode', form) ?? 'api'
  const selectedPlatform =
    mode === 'gui_pc_web' ? 'web' : mode === 'gui_android' ? 'android' : 'api'

  const profileOptions = (profiles.data ?? [])
    .filter((profile) => profile.platform === selectedPlatform)
    .map((profile) => ({ value: profile.name, label: profile.name }))

  const onSubmit = async (values: FormValues) => {
    const sample = {
      id: values.id || `quick-${Date.now()}`,
      prompts: values.prompts.split('\n').filter(Boolean),
      mode: values.mode,
      target_profile: values.target_profile,
      retry: 0,
      timeout_sec: values.mode === 'api' ? 60 : 180,
    }

    if (values.kind === 'sync') {
      try {
        setAsyncTaskId(undefined)
        setLastSyncResult(null)
        const result = (
          await client.post<SingleTestSyncResponse>('/tests/sync', sample, {
            timeout: values.mode === 'api' ? 60_000 : 240_000,
          })
        ).data
        setLastSyncResult(result)
      } catch (error) {
        message.error((error as Error).message)
      }
      return
    }

    try {
      setLastSyncResult(null)
      const result = await runAsync.mutateAsync(sample)
      setAsyncTaskId(result.task_id)
    } catch (error) {
      message.error((error as Error).message)
    }
  }

  const currentResult =
    lastSyncResult ??
    (asyncResult.data?.status === 'done' ||
    asyncResult.data?.status === 'failed' ||
    asyncResult.data?.status === 'timeout' ||
    asyncResult.data?.status === 'extraction_failed' ||
    asyncResult.data?.status === 'cancelled'
      ? asyncResult.data
      : undefined)
  const llmEnabled = hasLLMExtractionData(currentResult?.llm_responses, currentResult?.llm_errors)

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Typography.Title level={3}>单次测试</Typography.Title>
      <Card>
        <Form<FormValues>
          form={form}
          layout="vertical"
          onFinish={onSubmit}
          initialValues={{ kind: 'sync', mode: 'api' }}
        >
          <Form.Item name="id" label="ID（可留空自动生成）">
            <Input />
          </Form.Item>
          <Form.Item name="mode" label="模式">
            <Select
              options={[
                { label: 'API', value: 'api' },
                { label: 'Web (GUI)', value: 'gui_pc_web' },
                { label: 'Android (GUI)', value: 'gui_android' },
              ]}
            />
          </Form.Item>
          <Form.Item name="target_profile" label="Profile" rules={[{ required: true }]}>
            <Select options={profileOptions} placeholder="选择 profile" />
          </Form.Item>
          <Form.Item name="prompts" label="Prompts（每行一条）" rules={[{ required: true }]}>
            <Input.TextArea rows={4} />
          </Form.Item>
          <Form.Item name="kind" label="执行方式">
            <Radio.Group>
              <Radio value="sync">同步</Radio>
              <Radio value="async">异步</Radio>
            </Radio.Group>
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={runAsync.isPending}>
            运行
          </Button>
        </Form>
      </Card>

      {asyncTaskId && !currentResult ? (
        <Card>
          <Spin /> 异步任务运行中... (task_id: {asyncTaskId})
        </Card>
      ) : null}

      {currentResult ? (
        <Card title={`结果 · ${currentResult.status}`}>
          <Typography.Paragraph>
            duration: {currentResult.duration_ms ?? '-'} ms
          </Typography.Paragraph>
          {currentResult.error ? (
            <Typography.Paragraph type="danger">{currentResult.error}</Typography.Paragraph>
          ) : null}
          <Collapse
            defaultActiveKey={(currentResult.responses ?? []).map((_, index) => String(index))}
            items={(currentResult.responses ?? []).map((response, index) => ({
              key: String(index),
              forceRender: true,
              label: `第 ${index + 1} 轮响应`,
              children: (
                <ResponseComparison
                  ruleResponse={response}
                  llmResponse={currentResult.llm_responses?.[index]}
                  llmError={currentResult.llm_errors?.[index]}
                  llmEnabled={llmEnabled}
                />
              ),
            }))}
          />
        </Card>
      ) : null}
    </Space>
  )
}
