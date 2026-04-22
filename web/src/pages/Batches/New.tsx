import { InboxOutlined, MinusCircleOutlined, PlusOutlined } from '@ant-design/icons'
import {
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
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useCreateBatchJson, useUploadBatch } from '../../api/batches'
import { useProfiles } from '../../api/profiles'

interface JsonFormValues {
  name: string
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
  concurrency: number
  target_profile_default?: string
}

export function BatchNew() {
  const navigate = useNavigate()
  const { message } = App.useApp()
  const profiles = useProfiles()
  const createJson = useCreateBatchJson()
  const uploadBatch = useUploadBatch()
  const [uploaded, setUploaded] = useState<UploadFile | null>(null)

  const apiProfiles = (profiles.data ?? []).filter((profile) => profile.platform === 'api')
  const profileOptions = apiProfiles.map((profile) => ({
    value: profile.name,
    label: profile.name,
  }))

  const onJsonSubmit = async (values: JsonFormValues) => {
    try {
      const result = await createJson.mutateAsync({
        name: values.name,
        mode: 'api',
        concurrency: values.concurrency,
        target_profile_default: values.target_profile_default,
        webhook_url: values.webhook_url,
        samples: values.samples.map((sample) => ({
          id: sample.id,
          prompts: sample.prompts.split('\n').filter(Boolean),
          mode: 'api',
          target_profile: sample.target_profile ?? values.target_profile_default ?? '',
          new_session: sample.new_session,
        })),
      })
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
        mode: 'api',
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

  if (apiProfiles.length === 0) {
    return (
      <Card>
        <Typography.Paragraph>至少创建一个 API Profile 才能跑批次。</Typography.Paragraph>
        <Button type="primary" onClick={() => navigate('/profiles/new')}>
          去新建 Profile
        </Button>
      </Card>
    )
  }

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Typography.Title level={3}>新建批次</Typography.Title>
      <Tabs
        items={[
          {
            key: 'json',
            label: 'JSON 表单',
            children: (
              <Card>
                <Form<JsonFormValues>
                  layout="vertical"
                  initialValues={{ concurrency: 1, samples: [{ id: 's1', prompts: '' }] }}
                  onFinish={onJsonSubmit}
                >
                  <Form.Item name="name" label="名称" rules={[{ required: true }]}>
                    <Input />
                  </Form.Item>
                  <Form.Item name="concurrency" label="并发">
                    <InputNumber min={1} max={10} />
                  </Form.Item>
                  <Form.Item
                    name="target_profile_default"
                    label="默认 Profile"
                    rules={[{ required: true }]}
                  >
                    <Select options={profileOptions} />
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
                                placeholder="prompts（每行一条）"
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
              <Card>
                <Form<UploadFormValues>
                  layout="vertical"
                  initialValues={{ concurrency: 1 }}
                  onFinish={onUploadSubmit}
                >
                  <Form.Item name="name" label="名称" rules={[{ required: true }]}>
                    <Input />
                  </Form.Item>
                  <Form.Item name="concurrency" label="并发">
                    <InputNumber min={1} max={10} />
                  </Form.Item>
                  <Form.Item name="target_profile_default" label="默认 Profile">
                    <Select options={profileOptions} allowClear />
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
    </Space>
  )
}
