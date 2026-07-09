import {
  ArrowLeftOutlined,
  ExperimentOutlined,
  InboxOutlined,
  MinusCircleOutlined,
  PlusOutlined,
} from '@ant-design/icons'
import {
  Alert,
  App,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Tabs,
  Typography,
  Upload,
} from 'antd'
import type { UploadFile } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useCreateBatchJson, useUploadBatch } from '../../api/batches'
import { useProfiles } from '../../api/profiles'
import { EmptyState } from '../../components/states/EmptyState'
import { PageHeader } from '../../components/states/PageHeader'
import { ExecutionMode } from '../../types/api'
import { splitPrompts } from '../../utils/prompts'

interface JsonFormValues {
  name: string
  mode: ExecutionMode
  concurrency: number
  target_profile_default?: string
  webhook_url?: string
  samples: {
    id: string
    prompts: string
    target_profile?: string
    new_session?: boolean
  }[]
}

interface UploadFormValues {
  name: string
  mode: ExecutionMode
  concurrency: number
  target_profile_default?: string
}

const DRAFT_KEY = 'autoagent_batch_new_draft'
// Don't pester users with stale drafts older than this (covers "I left
// this tab open for a week"). 7 days is enough to recover crash/refresh
// without surfacing things they've moved on from.
const DRAFT_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000

interface Draft {
  ts: number
  values: Partial<JsonFormValues>
}

function readDraft(): Draft | null {
  try {
    const raw = localStorage.getItem(DRAFT_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Draft
    if (!parsed?.values || typeof parsed.ts !== 'number') return null
    if (Date.now() - parsed.ts > DRAFT_MAX_AGE_MS) return null
    return parsed
  } catch {
    return null
  }
}

function writeDraft(values: Partial<JsonFormValues>) {
  try {
    localStorage.setItem(DRAFT_KEY, JSON.stringify({ ts: Date.now(), values }))
  } catch {
    /* localStorage full / disabled */
  }
}

function clearDraft() {
  try {
    localStorage.removeItem(DRAFT_KEY)
  } catch {
    /* ignore */
  }
}

function isDraftMeaningful(values: Partial<JsonFormValues>): boolean {
  if (values.name && values.name.trim()) return true
  if (values.target_profile_default) return true
  if (values.webhook_url && values.webhook_url.trim()) return true
  const samples = values.samples ?? []
  return samples.some((s) => (s?.prompts ?? '').trim() || (s?.id ?? '').trim())
}

export function BatchNew() {
  const navigate = useNavigate()
  const { message } = App.useApp()
  const profiles = useProfiles()
  const createJson = useCreateBatchJson()
  const uploadBatch = useUploadBatch()
  const [uploaded, setUploaded] = useState<UploadFile | null>(null)
  const [jsonForm] = Form.useForm<JsonFormValues>()
  const [uploadForm] = Form.useForm<UploadFormValues>()
  const [pendingDraft, setPendingDraft] = useState<Draft | null>(() => readDraft())
  const draftSaveTimer = useRef<number | null>(null)

  const availableProfiles = profiles.data ?? []
  const jsonMode = Form.useWatch('mode', jsonForm) ?? 'api'
  const uploadMode = Form.useWatch('mode', uploadForm) ?? 'api'

  function modeToPlatform(mode: string): string {
    if (mode === 'gui_pc_web') return 'web'
    if (mode === 'gui_android') return 'android'
    if (mode === 'agent_pc') return 'agent_pc'
    if (mode === 'agent_android') return 'agent_android'
    return 'api'
  }

  const jsonPlatform = modeToPlatform(jsonMode)
  const uploadPlatform = modeToPlatform(uploadMode)
  const jsonProfileOptions = availableProfiles
    .filter((profile) => profile.platform === jsonPlatform)
    .map((profile) => ({ value: profile.name, label: profile.name }))
  const uploadProfileOptions = availableProfiles
    .filter((profile) => profile.platform === uploadPlatform)
    .map((profile) => ({ value: profile.name, label: profile.name }))

  // Persist the JSON-form draft 1.5s after the last edit. Throttling here
  // avoids hammering localStorage during fast typing.
  const onJsonValuesChange = (_changed: unknown, all: JsonFormValues) => {
    if (draftSaveTimer.current) window.clearTimeout(draftSaveTimer.current)
    draftSaveTimer.current = window.setTimeout(() => {
      if (isDraftMeaningful(all)) writeDraft(all)
      else clearDraft()
    }, 1500)
  }

  useEffect(() => {
    return () => {
      if (draftSaveTimer.current) window.clearTimeout(draftSaveTimer.current)
    }
  }, [])

  const restoreDraft = () => {
    if (!pendingDraft) return
    jsonForm.setFieldsValue(pendingDraft.values)
    setPendingDraft(null)
  }
  const dismissDraft = () => {
    clearDraft()
    setPendingDraft(null)
  }

  const onJsonSubmit = async (values: JsonFormValues) => {
    try {
      const result = await createJson.mutateAsync({
        name: values.name,
        mode: values.mode,
        concurrency: values.concurrency,
        target_profile_default: values.target_profile_default,
        webhook_url: values.webhook_url,
        samples: values.samples.map((sample) => ({
          id: sample.id,
          prompts: splitPrompts(sample.prompts),
          mode: values.mode,
          target_profile: sample.target_profile ?? values.target_profile_default ?? '',
          new_session: sample.new_session,
        })),
      })
      clearDraft()
      message.success('已创建')
      navigate(`/batches/${result.batch_id}`)
    } catch (error) {
      message.error((error as Error).message)
    }
  }

  const onUploadSubmit = async (values: UploadFormValues) => {
    if (!uploaded?.originFileObj) {
      message.error('请选择文件')
      return
    }

    try {
      const result = await uploadBatch.mutateAsync({
        name: values.name,
        mode: values.mode,
        concurrency: values.concurrency,
        target_profile_default: values.target_profile_default,
        file: uploaded.originFileObj,
      })
      message.success('已创建')
      navigate(`/batches/${result.batch_id}`)
    } catch (error) {
      message.error((error as Error).message)
    }
  }

  const breadcrumb = (
    <Space size={6}>
      <a onClick={() => navigate('/batches')} style={{ color: 'var(--aa-text-muted)' }}>
        <ArrowLeftOutlined /> 批次
      </a>
      <span>/ 新建</span>
    </Space>
  )

  if (profiles.data !== undefined && availableProfiles.length === 0) {
    return (
      <div>
        <PageHeader eyebrow={breadcrumb} title="新建批次" />
        <EmptyState
          icon={<ExperimentOutlined />}
          title="还没有可用的 Profile"
          description="批次需要绑定一个 profile 才能跑;先去创建一个,再回来。"
          action={
            <Button type="primary" onClick={() => navigate('/profiles/new')}>
              去新建 Profile
            </Button>
          }
        />
      </div>
    )
  }

  return (
    <div>
      <PageHeader
        eyebrow={breadcrumb}
        title="新建批次"
        subtitle="手动填表或上传 JSONL/JSON/CSV 文件,两种方式互斥。"
      />
      <Tabs
        items={[
          {
            key: 'json',
            label: 'JSON 表单',
            children: (
              <Card size="small">
                {pendingDraft && isDraftMeaningful(pendingDraft.values) ? (
                  <Alert
                    type="info"
                    showIcon
                    style={{ marginBottom: 12 }}
                    message={
                      <Space size={10}>
                        <span>检测到上次未提交的草稿</span>
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          {new Date(pendingDraft.ts).toLocaleString()}
                        </Typography.Text>
                      </Space>
                    }
                    action={
                      <Space size={6}>
                        <Button size="small" type="primary" onClick={restoreDraft}>
                          恢复
                        </Button>
                        <Button size="small" onClick={dismissDraft}>
                          丢弃
                        </Button>
                      </Space>
                    }
                  />
                ) : null}
                <Form<JsonFormValues>
                  form={jsonForm}
                  layout="vertical"
                  initialValues={{
                    mode: 'api',
                    concurrency: 1,
                    samples: [{ id: 's1', prompts: '' }],
                  }}
                  onValuesChange={onJsonValuesChange}
                  onFinish={onJsonSubmit}
                >
                  <Form.Item name="name" label="名称" rules={[{ required: true }]}>
                    <Input />
                  </Form.Item>
                  <Form.Item name="mode" label="模式" rules={[{ required: true }]}>
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
                  <Form.Item name="concurrency" label="并发">
                    <InputNumber min={1} max={10} />
                  </Form.Item>
                  {jsonMode === 'gui_android' || jsonMode === 'agent_android' ? (
                    <Typography.Text type="secondary">
                      Android 模式下，实际并发上限取决于在线可用设备数。
                    </Typography.Text>
                  ) : null}
                  <Form.Item
                    name="target_profile_default"
                    label="默认 Profile"
                    rules={[{ required: true }]}
                  >
                    <Select options={jsonProfileOptions} />
                  </Form.Item>
                  <Form.Item name="webhook_url" label="Webhook URL（可选）">
                    <Input />
                  </Form.Item>
                  <Typography.Title level={5}>Samples</Typography.Title>
                  <Form.List name="samples">
                    {(fields, { add, remove }) => (
                      <>
                        {fields.map((field) => (
                          <Space
                            key={field.key}
                            align="baseline"
                            style={{ display: 'flex', marginBottom: 8 }}
                          >
                            <Form.Item name={[field.name, 'id']} rules={[{ required: true }]}>
                              <Input placeholder="id" />
                            </Form.Item>
                            <Form.Item name={[field.name, 'prompts']} rules={[{ required: true }]}>
                              <Input.TextArea
                                rows={2}
                                placeholder="prompts（空行分隔多条，单条内可换行）"
                                style={{ width: 400 }}
                              />
                            </Form.Item>
                            <MinusCircleOutlined onClick={() => remove(field.name)} />
                          </Space>
                        ))}
                        <Button
                          type="dashed"
                          onClick={() => add({ id: '', prompts: '' })}
                          icon={<PlusOutlined />}
                          block
                        >
                          新增 sample
                        </Button>
                      </>
                    )}
                  </Form.List>
                  <Button
                    type="primary"
                    htmlType="submit"
                    loading={createJson.isPending}
                    style={{ marginTop: 16 }}
                  >
                    创建
                  </Button>
                </Form>
              </Card>
            ),
          },
          {
            key: 'upload',
            label: '文件上传',
            children: (
              <Card size="small">
                <Form<UploadFormValues>
                  form={uploadForm}
                  layout="vertical"
                  initialValues={{ mode: 'api', concurrency: 1 }}
                  onFinish={onUploadSubmit}
                >
                  <Form.Item name="name" label="名称" rules={[{ required: true }]}>
                    <Input />
                  </Form.Item>
                  <Form.Item name="mode" label="模式" rules={[{ required: true }]}>
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
                  <Form.Item name="concurrency" label="并发">
                    <InputNumber min={1} max={10} />
                  </Form.Item>
                  {uploadMode === 'gui_android' || uploadMode === 'agent_android' ? (
                    <Typography.Text type="secondary">
                      Android 模式下，实际并发上限取决于在线可用设备数。
                    </Typography.Text>
                  ) : null}
                  <Form.Item name="target_profile_default" label="默认 Profile">
                    <Select options={uploadProfileOptions} allowClear />
                  </Form.Item>
                  <Form.Item label="文件 (.jsonl / .json / .csv)">
                    <Upload.Dragger
                      multiple={false}
                      maxCount={1}
                      beforeUpload={() => false}
                      accept=".jsonl,.json,.csv"
                      onChange={(info) => setUploaded(info.fileList[0] ?? null)}
                    >
                      <p className="ant-upload-drag-icon">
                        <InboxOutlined />
                      </p>
                      <p>点击或拖拽文件到此处</p>
                    </Upload.Dragger>
                  </Form.Item>
                  <Button type="primary" htmlType="submit" loading={uploadBatch.isPending}>
                    创建
                  </Button>
                </Form>
              </Card>
            ),
          },
        ]}
      />
    </div>
  )
}
