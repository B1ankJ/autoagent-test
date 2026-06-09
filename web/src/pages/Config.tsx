import { Alert, App, Button, Card, Form, Input, InputNumber, Space, Switch } from 'antd'
import { useEffect, useState } from 'react'
import { LLMCheckResult, useDefaults, useSaveDefaults, useSaveVLM, useTestLLM, useVLM } from '../api/config'
import { PageHeader } from '../components/states/PageHeader'
import { GlobalDefaults, VLMConfig } from '../types/api'

const STAGE_TEXT: Record<LLMCheckResult['stage'], string> = {
  connect: '无法连接到该地址',
  auth: '认证失败',
  model_not_found: '模型不存在',
  response_shape: '返回格式异常',
  ok: '连通正常',
}

function saveErrorMessage(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: LLMCheckResult } } })?.response?.data?.detail
  if (detail?.stage) {
    return `${STAGE_TEXT[detail.stage] ?? '未知错误'}：${detail.message}`
  }
  return (error as Error).message
}

export function ConfigPage() {
  const vlm = useVLM()
  const defaults = useDefaults()
  const saveVlm = useSaveVLM()
  const testLlm = useTestLLM()
  const saveDefaults = useSaveDefaults()
  const [vlmForm] = Form.useForm<VLMConfig>()
  const [defaultsForm] = Form.useForm<GlobalDefaults>()
  const { message } = App.useApp()
  const [llmTestMessage, setLlmTestMessage] = useState<string | null>(null)
  const [llmTestOk, setLlmTestOk] = useState(false)

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

  const handleTestLLM = async () => {
    const values = vlmForm.getFieldsValue()
    if (!values.base_url || !values.model || !values.api_key) {
      setLlmTestOk(false)
      setLlmTestMessage('请先填写完整的 Base URL、Model 和 API Key')
      return
    }
    const result = await testLlm.mutateAsync({
      base_url: values.base_url,
      model: values.model,
      api_key: values.api_key,
    })
    setLlmTestOk(result.ok)
    setLlmTestMessage(
      result.ok
        ? `${STAGE_TEXT[result.stage]}（${result.latency_ms} ms）`
        : `${STAGE_TEXT[result.stage]}：${result.message}`,
    )
  }

  return (
    <div>
      <PageHeader
        eyebrow="系统"
        title="设置 Config"
        subtitle="VLM 凭据与运行时全局默认值"
      />
      <Space direction="vertical" size="large" style={{ width: '100%', maxWidth: 720 }}>

      <Card title="VLM" size="small">
        <Form
          form={vlmForm}
          layout="vertical"
          onFinish={async (values) => {
            try {
              await saveVlm.mutateAsync(values)
              message.success('已保存')
            } catch (error) {
              message.error(saveErrorMessage(error))
            }
          }}
        >
          <Form.Item name="base_url" label="Base URL" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="model" label="Model" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="api_key" label="API Key">
            <Input.Password />
          </Form.Item>
          <Space>
            <Button type="primary" htmlType="submit" loading={saveVlm.isPending}>
              保存
            </Button>
            <Button onClick={() => void handleTestLLM()} loading={testLlm.isPending}>
              测试连通性
            </Button>
          </Space>
          {llmTestMessage ? (
            <Alert
              style={{ marginTop: 12 }}
              type={llmTestOk ? 'success' : 'error'}
              showIcon
              message={llmTestMessage}
            />
          ) : null}
        </Form>
      </Card>

      <Card title="Global Defaults" size="small">
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
    </div>
  )
}
