import { CheckCircleOutlined, FileSearchOutlined, PlayCircleOutlined } from '@ant-design/icons'
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Empty,
  Form,
  Input,
  Select,
  Space,
  Steps,
  Tag,
  Typography,
} from 'antd'
import { useState } from 'react'

import {
  useCaptureProfileBuilderStep,
  useCreateProfileBuilderSession,
  useGenerateProfileBuilderDraft,
} from '../../api/profileBuilder'
import { useDevices } from '../../api/devices'
import { Device, ProfileBuilderDraftResponse, ProfileBuilderSessionView, ReviewItem } from '../../types/api'

const CAPTURE_STEPS = [
  { key: 'idle', title: 'Capture Idle State', description: '停在对话页空闲态后采集。' },
  { key: 'editing', title: 'Capture Editing State', description: '点开输入框进入编辑态后采集。' },
  { key: 'response', title: 'Capture Response State', description: '发送一条测试消息并等待回复后采集。' },
] as const

function deviceLabel(device: Device) {
  return device.label || device.model || device.serial
}

function reviewOptionText(value: ReviewItem['recommended_option']) {
  if ('type' in value) {
    return `${value.type}: ${value.value}`
  }
  return [
    `response=${value.response_container_locator.value}`,
    `scroll=${value.scroll_container_locator.value}`,
    `bubble=${value.latest_bubble_match.value}`,
  ].join('\n')
}

export default function Builder() {
  const devices = useDevices()
  const createSession = useCreateProfileBuilderSession()
  const captureStep = useCaptureProfileBuilderStep()
  const generateDraft = useGenerateProfileBuilderDraft()
  const { message } = App.useApp()

  const [selectedDevice, setSelectedDevice] = useState<string>()
  const [profileName, setProfileName] = useState('qwen_android')
  const [session, setSession] = useState<ProfileBuilderSessionView | null>(null)
  const [draft, setDraft] = useState<ProfileBuilderDraftResponse | null>(null)

  const onlineAndroidDevices = (devices.data ?? []).filter((device) => device.online && device.enabled)
  const completedSteps = new Set(session?.captures.map((capture) => capture.step) ?? [])

  const startSession = async () => {
    if (!selectedDevice || !profileName.trim()) {
      message.warning('请选择设备并填写 profile 名称')
      return
    }
    try {
      const nextSession = await createSession.mutateAsync({
        platform: 'android',
        device_serial: selectedDevice,
        name: profileName.trim(),
      })
      setSession(nextSession)
      setDraft(null)
      message.success('Builder session 已创建')
    } catch (error) {
      message.error((error as Error).message)
    }
  }

  const runCapture = async (step: string) => {
    if (!session) {
      return
    }
    try {
      const nextSession = await captureStep.mutateAsync({ sessionId: session.id, step })
      setSession(nextSession)
      setDraft(null)
      message.success(`${step} capture 已保存`)
    } catch (error) {
      message.error((error as Error).message)
    }
  }

  const runDraft = async () => {
    if (!session) {
      return
    }
    try {
      const nextDraft = await generateDraft.mutateAsync(session.id)
      setSession(nextDraft.session)
      setDraft(nextDraft)
      message.success('Draft profile 已生成')
    } catch (error) {
      message.error((error as Error).message)
    }
  }

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Typography.Title level={3} style={{ margin: 0 }}>
        Build Profile
      </Typography.Title>

      <Card title="Session Setup">
        <Form layout="vertical">
          <Form.Item label="Android Device">
            <Select
              placeholder="选择在线设备"
              loading={devices.isLoading}
              value={selectedDevice}
              onChange={setSelectedDevice}
              options={onlineAndroidDevices.map((device) => ({
                label: deviceLabel(device),
                value: device.serial,
              }))}
            />
          </Form.Item>
          <Form.Item label="Profile Name">
            <Input value={profileName} onChange={(event) => setProfileName(event.target.value)} />
          </Form.Item>
          <Space>
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              loading={createSession.isPending}
              onClick={startSession}
            >
              Start Builder Session
            </Button>
            <Button
              disabled
              icon={<CheckCircleOutlined />}
              title="Connectivity validation comes in the next task."
            >
              Run Connectivity Test
            </Button>
          </Space>
        </Form>
      </Card>

      <Card title="Capture Steps">
        <Steps
          direction="vertical"
          items={CAPTURE_STEPS.map((step) => ({
            title: step.title,
            description: (
              <Space direction="vertical" size="small">
                <Typography.Text type="secondary">{step.description}</Typography.Text>
                <Space>
                  {completedSteps.has(step.key) ? <Tag color="green">Captured</Tag> : <Tag>Pending</Tag>}
                  <Button
                    size="small"
                    onClick={() => runCapture(step.key)}
                    loading={captureStep.isPending}
                    disabled={!session}
                  >
                    Capture
                  </Button>
                </Space>
              </Space>
            ),
          }))}
        />
        <Button
          style={{ marginTop: 16 }}
          icon={<FileSearchOutlined />}
          type="primary"
          onClick={runDraft}
          loading={generateDraft.isPending}
          disabled={!session || completedSteps.size !== CAPTURE_STEPS.length}
        >
          Generate Draft
        </Button>
      </Card>

      {session ? (
        <Card title="Session State">
          <Descriptions column={1} size="small">
            <Descriptions.Item label="Session ID">{session.id}</Descriptions.Item>
            <Descriptions.Item label="Status">{session.status}</Descriptions.Item>
            <Descriptions.Item label="Artifacts">{session.artifacts.join(', ') || '-'}</Descriptions.Item>
          </Descriptions>
        </Card>
      ) : null}

      <Card title="Review Items">
        {!draft?.review_items.length ? (
          <Empty description="先完成 capture 并生成 draft" />
        ) : (
          <Space direction="vertical" style={{ width: '100%' }}>
            {draft.review_items.map((item, index) => (
              <Alert
                key={`${item.field}-${index}`}
                type="warning"
                showIcon
                message={`${item.field}: ${item.reason}`}
                description={
                  <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>
                    {reviewOptionText(item.recommended_option)}
                  </Typography.Paragraph>
                }
              />
            ))}
          </Space>
        )}
      </Card>

      <Card title="Draft YAML">
        {draft ? (
          <Input.TextArea
            readOnly
            autoSize={{ minRows: 12, maxRows: 24 }}
            value={draft.draft_profile_yaml}
          />
        ) : (
          <Empty description="尚未生成 draft profile" />
        )}
      </Card>
    </Space>
  )
}
