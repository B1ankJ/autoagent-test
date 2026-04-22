import { App, Button, Card, Form, Input, InputNumber, Space, Switch, Typography } from 'antd'
import { useEffect } from 'react'
import { useDefaults, useSaveDefaults, useSaveVLM, useVLM } from '../api/config'
import { GlobalDefaults, VLMConfig } from '../types/api'

export function ConfigPage() {
  const vlm = useVLM()
  const defaults = useDefaults()
  const saveVlm = useSaveVLM()
  const saveDefaults = useSaveDefaults()
  const [vlmForm] = Form.useForm<VLMConfig>()
  const [defaultsForm] = Form.useForm<GlobalDefaults>()
  const { message } = App.useApp()

  useEffect(() => {
    if (vlm.data) {
      vlmForm.setFieldsValue(vlm.data)
    }
  }, [vlm.data, vlmForm])

  useEffect(() => {
    if (defaults.data) {
      defaultsForm.setFieldsValue(defaults.data)
    }
  }, [defaults.data, defaultsForm])

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Typography.Title level={3}>Config</Typography.Title>

      <Card title="VLM">
        <Form
          form={vlmForm}
          layout="vertical"
          onFinish={async (values) => {
            try {
              await saveVlm.mutateAsync(values)
              message.success('已保存')
            } catch (error) {
              message.error((error as Error).message)
            }
          }}
        >
          <Form.Item name="base_url" label="Base URL" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="model" label="Model" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="api_key_env" label="API Key Env Var" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={saveVlm.isPending}>
            保存
          </Button>
        </Form>
      </Card>

      <Card title="Global Defaults">
        <Form
          form={defaultsForm}
          layout="vertical"
          onFinish={async (values) => {
            try {
              await saveDefaults.mutateAsync(values)
              message.success('已保存')
            } catch (error) {
              message.error((error as Error).message)
            }
          }}
        >
          <Form.Item name="api_timeout_sec" label="API timeout (s)">
            <InputNumber min={1} />
          </Form.Item>
          <Form.Item name="gui_timeout_sec" label="GUI timeout (s)">
            <InputNumber min={1} />
          </Form.Item>
          <Form.Item name="retry" label="Retry">
            <InputNumber min={0} max={10} />
          </Form.Item>
          <Form.Item name="concurrency" label="Concurrency">
            <InputNumber min={1} max={10} />
          </Form.Item>
          <Form.Item name="verbose_logs" label="Verbose logs" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={saveDefaults.isPending}>
            保存
          </Button>
        </Form>
      </Card>
    </Space>
  )
}
