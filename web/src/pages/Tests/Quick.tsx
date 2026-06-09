import { DeleteOutlined, HistoryOutlined } from '@ant-design/icons'
import {
  App,
  Button,
  Card,
  Collapse,
  Dropdown,
  Form,
  Input,
  Radio,
  Select,
  Space,
  Spin,
  Typography,
} from 'antd'
import type { MenuProps } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { client } from '../../api/client'
import { ResponseComparison } from '../../components/ResponseComparison'
import { PageHeader } from '../../components/states/PageHeader'
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

interface HistoryEntry {
  ts: number
  mode: ExecutionMode
  target_profile: string
  prompts: string
  kind: 'sync' | 'async'
}

const HISTORY_KEY = 'autoagent_quick_history'
const HISTORY_MAX = 10

function readHistory(): HistoryEntry[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as HistoryEntry[]
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function writeHistory(entries: HistoryEntry[]) {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(entries.slice(0, HISTORY_MAX)))
  } catch {
    /* localStorage full / disabled — silently drop */
  }
}

function shortPreview(prompts: string): string {
  const first = prompts.split('\n')[0] ?? ''
  return first.length > 36 ? `${first.slice(0, 36)}…` : first || '(空 prompt)'
}

export function TestsQuick() {
  const [form] = Form.useForm<FormValues>()
  const profiles = useProfiles()
  const runAsync = useRunAsync()
  const [asyncTaskId, setAsyncTaskId] = useState<string | undefined>()
  const asyncResult = useAsyncResult(asyncTaskId)
  const { message } = App.useApp()
  const [lastSyncResult, setLastSyncResult] = useState<SingleTestSyncResponse | null>(null)
  const [history, setHistory] = useState<HistoryEntry[]>(() => readHistory())
  const mode = Form.useWatch('mode', form) ?? 'api'
  const selectedPlatform =
    mode === 'gui_pc_web'
      ? 'web'
      : mode === 'gui_android'
        ? 'android'
        : mode === 'agent_pc'
          ? 'agent_pc'
          : mode === 'agent_android'
            ? 'agent_android'
            : 'api'

  const profileOptions = (profiles.data ?? [])
    .filter((profile) => profile.platform === selectedPlatform)
    .map((profile) => ({ value: profile.name, label: profile.name }))

  const pushHistory = useCallback((values: FormValues) => {
    setHistory((prev) => {
      const entry: HistoryEntry = {
        ts: Date.now(),
        mode: values.mode,
        target_profile: values.target_profile,
        prompts: values.prompts,
        kind: values.kind,
      }
      // Drop any prior duplicate (same mode/profile/prompts) so repeat runs
      // don't fill the dropdown with the same row over and over.
      const filtered = prev.filter(
        (h) =>
          !(
            h.mode === entry.mode &&
            h.target_profile === entry.target_profile &&
            h.prompts === entry.prompts
          ),
      )
      const next = [entry, ...filtered].slice(0, HISTORY_MAX)
      writeHistory(next)
      return next
    })
  }, [])

  const clearHistory = () => {
    setHistory([])
    writeHistory([])
  }

  const fillFromHistory = (entry: HistoryEntry) => {
    form.setFieldsValue({
      mode: entry.mode,
      target_profile: entry.target_profile,
      prompts: entry.prompts,
      kind: entry.kind,
    })
  }

  // Refresh state when this tab gets focus — another tab might have run
  // a quick test and pushed to localStorage.
  useEffect(() => {
    const onFocus = () => setHistory(readHistory())
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [])

  const historyMenuItems: MenuProps['items'] = history.length
    ? [
        ...history.map((entry, idx) => ({
          key: String(idx),
          label: (
            <Space direction="vertical" size={0} style={{ maxWidth: 360 }}>
              <Space size={8}>
                <span className="aa-mono" style={{ fontSize: 11, color: 'var(--aa-cobalt)' }}>
                  {entry.mode}
                </span>
                <span style={{ fontSize: 12 }}>{entry.target_profile}</span>
                <span style={{ fontSize: 11, color: 'var(--aa-text-muted)' }}>
                  {new Date(entry.ts).toLocaleString()}
                </span>
              </Space>
              <span style={{ fontSize: 12, color: 'var(--aa-text-muted)' }}>
                {shortPreview(entry.prompts)}
              </span>
            </Space>
          ),
          onClick: () => fillFromHistory(entry),
        })),
        { type: 'divider' as const },
        {
          key: 'clear',
          icon: <DeleteOutlined />,
          label: '清空历史',
          danger: true,
          onClick: clearHistory,
        },
      ]
    : [{ key: 'empty', disabled: true, label: '还没有历史记录' }]

  const onSubmit = async (values: FormValues) => {
    const sample = {
      id: values.id || `quick-${Date.now()}`,
      prompts: values.prompts.split('\n').filter(Boolean),
      mode: values.mode,
      target_profile: values.target_profile,
      retry: 0,
      timeout_sec: values.mode === 'api' ? 60 : values.mode.startsWith('agent') ? 600 : 180,
    }

    pushHistory(values)

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
    <div>
      <PageHeader
        eyebrow="任务"
        title="单次测试 Quick Test"
        subtitle="试一条 prompt,验证 profile 是否生效;同步立等结果,异步走 task_id 轮询。"
        extra={
          <Dropdown menu={{ items: historyMenuItems }} trigger={['click']}>
            <Button icon={<HistoryOutlined />}>
              历史 {history.length > 0 ? `(${history.length})` : ''}
            </Button>
          </Dropdown>
        }
      />
      <Space direction="vertical" size="large" style={{ width: '100%', maxWidth: 880 }}>
      <Card size="small">
        <Form<FormValues>
          form={form}
          layout="vertical"
          onFinish={onSubmit}
          initialValues={{ kind: 'sync', mode: 'api' }}
        >
          <Form.Item name="id" label="ID(可留空自动生成)">
            <Input />
          </Form.Item>
          <Form.Item name="mode" label="模式">
            <Select
              options={[
                { label: 'API', value: 'api' },
                { label: 'Web (GUI)', value: 'gui_pc_web' },
                { label: 'Android (GUI)', value: 'gui_android' },
                { label: 'Agent PC', value: 'agent_pc' },
                { label: 'Agent Android', value: 'agent_android' },
              ]}
            />
          </Form.Item>
          <Form.Item name="target_profile" label="Profile" rules={[{ required: true }]}>
            <Select options={profileOptions} placeholder="选择 profile" />
          </Form.Item>
          <Form.Item name="prompts" label="Prompts(每行一条)" rules={[{ required: true }]}>
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
        <Card size="small">
          <Spin /> 异步任务运行中...{' '}
          <span className="aa-mono aa-muted">task_id: {asyncTaskId}</span>
        </Card>
      ) : null}

      {currentResult ? (
        <Card size="small" title={`结果 · ${currentResult.status}`}>
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
    </div>
  )
}
