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
import { useProfiles } from '../../api/profiles'
import { useAsyncResult, useRunAsync, useRunSync } from '../../api/tests'
import { SingleTestSyncResponse } from '../../types/api'

interface FormValues {
  id?: string
  target_profile: string
  prompts: string
  kind: 'sync' | 'async'
}

export function TestsQuick() {
  const profiles = useProfiles()
  const runSync = useRunSync()
  const runAsync = useRunAsync()
  const [asyncTaskId, setAsyncTaskId] = useState<string | undefined>()
  const asyncResult = useAsyncResult(asyncTaskId)
  const { message } = App.useApp()
  const [lastSyncResult, setLastSyncResult] = useState<SingleTestSyncResponse | null>(null)

  const apiProfiles = (profiles.data ?? []).filter((profile) => profile.platform === 'api')

  const onSubmit = async (values: FormValues) => {
    const sample = {
      id: values.id || `quick-${Date.now()}`,
      prompts: values.prompts.split('\n').filter(Boolean),
      mode: 'api' as const,
      target_profile: values.target_profile,
    }

    if (values.kind === 'sync') {
      try {
        setAsyncTaskId(undefined)
        setLastSyncResult(null)
        const result = await runSync.mutateAsync(sample)
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

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Typography.Title level={3}>单次测试</Typography.Title>
      <Card>
        <Form<FormValues> layout="vertical" onFinish={onSubmit} initialValues={{ kind: 'sync' }}>
          <Form.Item name="id" label="ID（可留空自动生成）">
            <Input />
          </Form.Item>
          <Form.Item name="target_profile" label="Profile" rules={[{ required: true }]}>
            <Select
              options={apiProfiles.map((profile) => ({ value: profile.name, label: profile.name }))}
              placeholder="选择 API profile"
            />
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
          <Button
            type="primary"
            htmlType="submit"
            loading={runSync.isPending || runAsync.isPending}
          >
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
            items={(currentResult.responses ?? []).map((response, index) => ({
              key: String(index),
              label: `第 ${index + 1} 轮响应`,
              children: (
                <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>
                  {response}
                </Typography.Paragraph>
              ),
            }))}
          />
        </Card>
      ) : null}
    </Space>
  )
}
