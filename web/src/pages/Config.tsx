import { Alert, App, Button, Card, Form, Input, InputNumber, Space, Switch, Typography } from 'antd'
import { useEffect, useState } from 'react'
import {
  DingTalkConfig,
  LLMCheckResult,
  useDefaults,
  useNotifications,
  useRemoveWhitelist,
  useSaveDefaults,
  useSaveNotifications,
  useSaveVLM,
  useTestLLM,
  useTestNotifications,
  useVLM,
  useWhitelist,
} from '../api/config'
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
  const notifications = useNotifications()
  const saveNotifications = useSaveNotifications()
  const testNotifications = useTestNotifications()
  const whitelist = useWhitelist()
  const removeWhitelist = useRemoveWhitelist()
  const [vlmForm] = Form.useForm<VLMConfig>()
  const [defaultsForm] = Form.useForm<GlobalDefaults>()
  const [notifyForm] = Form.useForm<DingTalkConfig>()
  const [notifyTestMsg, setNotifyTestMsg] = useState<string | null>(null)
  const [notifyTestOk, setNotifyTestOk] = useState(false)
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

  useEffect(() => {
    if (notifications.data) {
      notifyForm.setFieldsValue(notifications.data)
    }
  }, [notifications.data, notifyForm])

  const handleTestNotify = async () => {
    const values = notifyForm.getFieldsValue()
    if (!values.webhook_url?.trim()) {
      setNotifyTestOk(false)
      setNotifyTestMsg('请先填写 Webhook URL')
      return
    }
    try {
      const result = await testNotifications.mutateAsync(values)
      setNotifyTestOk(result.ok)
      setNotifyTestMsg(
        result.ok
          ? '✅ 测试消息已发送,请检查群里是否收到'
          : `❌ 发送失败: ${result.errmsg ?? 'unknown'} (status=${result.status_code ?? '-'}, errcode=${result.errcode ?? '-'})`,
      )
    } catch (e) {
      setNotifyTestOk(false)
      setNotifyTestMsg((e as Error).message)
    }
  }

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

      <Card title="钉钉通知" size="small">
        <Alert
          style={{ marginBottom: 12 }}
          type="info"
          showIcon
          message="规则:同一设备连续 N 个 sample 响应为空(status=done 且 responses[0] 为空) → 自动钉钉提醒。"
        />
        <Form
          form={notifyForm}
          layout="vertical"
          onFinish={async (values) => {
            try {
              await saveNotifications.mutateAsync(values)
              message.success('已保存')
            } catch (error) {
              message.error((error as Error).message)
            }
          }}
        >
          <Form.Item name="enabled" label="启用通知" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item
            name="webhook_url"
            label="Webhook URL"
            extra="钉钉自定义机器人的 webhook 地址"
          >
            <Input placeholder="https://oapi.dingtalk.com/robot/send?access_token=..." />
          </Form.Item>
          <Form.Item
            name="secret"
            label="Secret(可选,加签模式)"
            extra="如果机器人安全设置选了「加签」,填这里;否则留空"
          >
            <Input.Password placeholder="SEC..." />
          </Form.Item>
          <Form.Item
            name="empty_response_threshold"
            label="连续空响应阈值"
            extra="规则 1:同一设备连续多少次空响应触发通知"
          >
            <InputNumber min={1} max={20} />
          </Form.Item>
          <Form.Item
            name="same_response_enabled"
            label="启用重复响应检测"
            valuePropName="checked"
            extra="规则 2:同设备连续 N 次响应一样 → 截图给 VLM 判断是否还是聊天页;白名单按 profile 维度(需 VLM 已配置)"
          >
            <Switch />
          </Form.Item>
          <Form.Item
            name="same_response_threshold"
            label="连续相同响应阈值"
          >
            <InputNumber min={1} max={20} />
          </Form.Item>
          <Form.Item name="at_all" label="@ 全体" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Space>
            <Button type="primary" htmlType="submit" loading={saveNotifications.isPending}>
              保存
            </Button>
            <Button
              onClick={() => void handleTestNotify()}
              loading={testNotifications.isPending}
            >
              发送测试消息
            </Button>
          </Space>
          {notifyTestMsg ? (
            <Alert
              style={{ marginTop: 12 }}
              type={notifyTestOk ? 'success' : 'error'}
              showIcon
              message={notifyTestMsg}
            />
          ) : null}
        </Form>
      </Card>

      <Card
        title="重复响应白名单"
        size="small"
        extra={
          <Button size="small" onClick={() => whitelist.refetch()}>
            刷新
          </Button>
        }
      >
        <Alert
          style={{ marginBottom: 12 }}
          type="info"
          showIcon
          message="规则 2 命中且 VLM 判定页面正常时,响应会被自动加入这里。后续同样的响应不再触发判断/告警。"
        />
        {whitelist.data && whitelist.data.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {whitelist.data.map((entry, idx) => (
              <div
                key={`${entry.target_profile}-${idx}`}
                style={{
                  border: '1px solid var(--aa-border, #eee)',
                  borderRadius: 6,
                  padding: 8,
                  display: 'flex',
                  alignItems: 'start',
                  gap: 8,
                }}
              >
                <div style={{ flex: 1, fontSize: 12 }}>
                  <div className="aa-mono">profile: {entry.target_profile}</div>
                  <div className="aa-muted" style={{ marginTop: 4 }}>
                    {entry.response_excerpt || '(空)'}
                  </div>
                  <div className="aa-muted" style={{ fontSize: 11, marginTop: 2 }}>
                    {new Date(entry.added_at).toLocaleString()}
                  </div>
                </div>
                <Button
                  size="small"
                  danger
                  loading={removeWhitelist.isPending}
                  onClick={() =>
                    removeWhitelist
                      .mutateAsync({
                        target_profile: entry.target_profile,
                        response: entry.response,
                      })
                      .catch((e) => message.error((e as Error).message))
                  }
                >
                  删除
                </Button>
              </div>
            ))}
          </div>
        ) : (
          <Typography.Text type="secondary">还没有白名单记录。</Typography.Text>
        )}
      </Card>
      </Space>
    </div>
  )
}
