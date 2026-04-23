import { CheckCircleOutlined, FileSearchOutlined, PlayCircleOutlined } from '@ant-design/icons'
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Empty,
  Form,
  Image,
  Input,
  List,
  Row,
  Select,
  Space,
  Steps,
  Tag,
  Typography,
  Col,
} from 'antd'
import { useEffect, useState } from 'react'

import {
  useApplyProfileBuilderReview,
  useCaptureProfileBuilderStep,
  useCreateProfileBuilderSession,
  useGenerateProfileBuilderDraft,
  useValidateProfileBuilderDraft,
} from '../../api/profileBuilder'
import {
  fetchProfileBuilderArtifactBlobUrl,
  useProfileBuilderRuntime,
} from '../../api/profileBuilderRuntime'
import { useDevices } from '../../api/devices'
import {
  Device,
  ProfileBuilderDraftResponse,
  ProfileBuilderRuntimeView,
  ProfileBuilderSessionView,
  ReviewItem,
} from '../../types/api'

const CAPTURE_STEPS = [
  { key: 'idle', title: 'Capture Idle State', description: '停在对话页空闲态后采集。' },
  { key: 'editing', title: 'Capture Editing State', description: '点开输入框进入编辑态后采集。' },
  { key: 'response', title: 'Capture Response State', description: '发送一条测试消息并等待回复后采集。' },
] as const

function deviceLabel(device: Device) {
  return device.label || device.model || device.serial
}

function runtimeStepStatus(
  runtime: ProfileBuilderRuntimeView | undefined,
  key: string,
): 'wait' | 'process' | 'finish' | 'error' {
  if (!runtime) {
    return 'wait'
  }
  if (key === 'draft') {
    if (runtime.session_status === 'ready' || runtime.session_status === 'validated') {
      return 'finish'
    }
    return runtime.current_step === 'generate_draft' ? 'process' : 'wait'
  }
  if (key === 'connectivity') {
    if (runtime.connectivity.status === 'done') {
      return 'finish'
    }
    if (runtime.connectivity.status === 'failed') {
      return 'error'
    }
    if (runtime.connectivity.status === 'running') {
      return 'process'
    }
    return 'wait'
  }
  const capture = runtime.captures.find((item) => item.step === key)
  switch (capture?.status) {
    case 'done':
      return 'finish'
    case 'running':
      return 'process'
    case 'failed':
      return 'error'
    default:
      return 'wait'
  }
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

function toReviewPayload(
  field: string,
  value: ReviewItem['recommended_option'],
): Record<string, unknown> {
  if ('type' in value) {
    return { [field]: value }
  }
  return {
    response_extraction: {
      response_container_locator: value.response_container_locator,
      scroll_container_locator: value.scroll_container_locator,
      latest_bubble_match: value.latest_bubble_match,
    },
  }
}

export default function Builder() {
  const devices = useDevices()
  const createSession = useCreateProfileBuilderSession()
  const captureStep = useCaptureProfileBuilderStep()
  const generateDraft = useGenerateProfileBuilderDraft()
  const applyReview = useApplyProfileBuilderReview()
  const validateDraft = useValidateProfileBuilderDraft()
  const { message } = App.useApp()

  const [selectedDevice, setSelectedDevice] = useState<string>()
  const [profileName, setProfileName] = useState('qwen_android')
  const [session, setSession] = useState<ProfileBuilderSessionView | null>(null)
  const [draft, setDraft] = useState<ProfileBuilderDraftResponse | null>(null)
  const [connectivitySummary, setConnectivitySummary] = useState<string | null>(null)
  const [currentScreenUrl, setCurrentScreenUrl] = useState<string | null>(null)
  const [selectedScreenPath, setSelectedScreenPath] = useState<string | null>(null)
  const [followLatestScreen, setFollowLatestScreen] = useState(true)
  const runtime = useProfileBuilderRuntime(session?.id)

  const onlineAndroidDevices = (devices.data ?? []).filter((device) => device.online && device.enabled)
  const completedSteps = new Set(session?.captures.map((capture) => capture.step) ?? [])
  const runtimeData = runtime.data
  const availableScreens = runtimeData
    ? [...runtimeData.recent_screens, ...runtimeData.connectivity.screens].filter(
        (screen, index, all) => all.findIndex((candidate) => candidate.path === screen.path) === index,
      )
    : []
  const latestScreen = availableScreens[availableScreens.length - 1] ?? null
  const currentScreen =
    availableScreens.find((screen) => screen.path === selectedScreenPath) ??
    (followLatestScreen ? latestScreen : latestScreen)

  useEffect(() => {
    if (!latestScreen) {
      setSelectedScreenPath(null)
      return
    }
    if (followLatestScreen || !selectedScreenPath) {
      setSelectedScreenPath(latestScreen.path)
    }
  }, [followLatestScreen, latestScreen?.path, selectedScreenPath])

  useEffect(() => {
    const revokeObjectUrl = (value: string) => {
      if (typeof URL.revokeObjectURL === 'function') {
        URL.revokeObjectURL(value)
      }
    }
    let revokedUrl: string | null = null
    let cancelled = false

    async function loadPreview() {
      if (!session?.id || !currentScreen?.path) {
        setCurrentScreenUrl(null)
        return
      }
      try {
        const url = await fetchProfileBuilderArtifactBlobUrl(session.id, currentScreen.path)
        if (cancelled) {
          revokeObjectUrl(url)
          return
        }
        setCurrentScreenUrl((previous) => {
          if (previous) {
            revokeObjectUrl(previous)
          }
          revokedUrl = url
          return url
        })
      } catch {
        if (!cancelled) {
          setCurrentScreenUrl(null)
        }
      }
    }

    void loadPreview()

    return () => {
      cancelled = true
      if (revokedUrl) {
        revokeObjectUrl(revokedUrl)
      }
    }
  }, [currentScreen?.path, session?.id])

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
      setConnectivitySummary(null)
      setCurrentScreenUrl(null)
      setSelectedScreenPath(null)
      setFollowLatestScreen(true)
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
      setConnectivitySummary(null)
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
      setConnectivitySummary(null)
      message.success('Draft profile 已生成')
    } catch (error) {
      message.error((error as Error).message)
    }
  }

  const chooseReviewOption = async (
    item: ReviewItem,
    option: ReviewItem['recommended_option'],
  ) => {
    if (!session || !draft) {
      return
    }
    try {
      const updated = await applyReview.mutateAsync({
        sessionId: session.id,
        payload: toReviewPayload(item.field, option),
      })
      setSession(updated.session)
      setDraft({
        ...draft,
        session: updated.session,
        draft_profile_yaml: updated.draft_profile_yaml,
        review_items: draft.review_items.filter((reviewItem) => reviewItem !== item),
      })
      message.success(`${item.field} 已更新`)
    } catch (error) {
      message.error((error as Error).message)
    }
  }

  const runConnectivityValidation = async () => {
    if (!session || !draft) {
      return
    }
    try {
      const validated = await validateDraft.mutateAsync(session.id)
      setSession(validated.session)
      setDraft({
        ...draft,
        session: validated.session,
        draft_profile_yaml: validated.draft_profile_yaml,
      })
      setConnectivitySummary(
        validated.connectivity_result.status === 'done'
          ? validated.connectivity_result.responses[0] ?? 'done'
          : validated.connectivity_result.error ?? validated.connectivity_result.status,
      )
      message.success('Connectivity test 已完成')
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
              disabled={!draft}
              icon={<CheckCircleOutlined />}
              loading={validateDraft.isPending}
              onClick={runConnectivityValidation}
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

      {session ? (
        <Row gutter={16} align="top">
          <Col xs={24} lg={14}>
            <Card title="Runtime Status" loading={runtime.isLoading && !runtimeData}>
              {runtimeData ? (
                <Space direction="vertical" style={{ width: '100%' }} size="middle">
                  <Alert
                    type={runtimeData.last_error ? 'error' : 'info'}
                    message={`Current Step: ${runtimeData.current_step}`}
                    description={
                      runtimeData.last_error
                        ? runtimeData.last_error
                        : `session=${runtimeData.session_status} step=${runtimeData.step_state}`
                    }
                    showIcon
                  />
                  <Steps
                    direction="vertical"
                    size="small"
                    items={[
                      ...CAPTURE_STEPS.map((step) => ({
                        title: step.title,
                        status: runtimeStepStatus(runtimeData, step.key),
                      })),
                      {
                        title: 'Generate Draft',
                        status: runtimeStepStatus(runtimeData, 'draft'),
                      },
                      {
                        title: 'Run Connectivity Test',
                        status: runtimeStepStatus(runtimeData, 'connectivity'),
                      },
                    ]}
                  />
                </Space>
              ) : (
                <Empty description="启动 session 后自动显示运行状态" />
              )}
            </Card>
          </Col>
          <Col xs={24} lg={10}>
            <Card title="Key Screens" loading={runtime.isLoading && !runtimeData}>
              {!runtimeData || (!currentScreen && runtimeData.recent_screens.length === 0) ? (
                <Empty description="暂无关键截图" />
              ) : (
                <Space direction="vertical" style={{ width: '100%' }} size="middle">
                  {currentScreen ? (
                    <>
                      <Typography.Text strong>{currentScreen.label}</Typography.Text>
                      {currentScreenUrl ? (
                        <Image src={currentScreenUrl} alt={currentScreen.label} />
                      ) : (
                        <Alert type="warning" showIcon message="截图加载失败" />
                      )}
                    </>
                  ) : null}
                  <Space>
                    <Tag color={followLatestScreen ? 'blue' : 'default'}>
                      {followLatestScreen ? 'Following Latest' : 'Manual Selection'}
                    </Tag>
                    <Button
                      size="small"
                      onClick={() => {
                        setFollowLatestScreen(true)
                        if (latestScreen) {
                          setSelectedScreenPath(latestScreen.path)
                        }
                      }}
                      disabled={!latestScreen || followLatestScreen}
                    >
                      Follow Latest
                    </Button>
                  </Space>
                  <List
                    size="small"
                    dataSource={availableScreens.slice().reverse()}
                    renderItem={(item) => (
                      <List.Item
                        style={{
                          cursor: 'pointer',
                          background:
                            item.path === currentScreen?.path ? 'rgba(22, 119, 255, 0.08)' : undefined,
                          borderRadius: 8,
                          paddingInline: 8,
                        }}
                        onClick={() => {
                          setFollowLatestScreen(false)
                          setSelectedScreenPath(item.path)
                        }}
                      >
                        <Space direction="vertical" size={0} style={{ width: '100%' }}>
                          <Typography.Text strong={item.path === currentScreen?.path}>
                            {item.label}
                          </Typography.Text>
                          <Typography.Text type="secondary">{item.step}</Typography.Text>
                          <Typography.Text type="secondary">
                            {new Date(item.taken_at).toLocaleString()}
                          </Typography.Text>
                        </Space>
                      </List.Item>
                    )}
                  />
                </Space>
              )}
            </Card>
          </Col>
        </Row>
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
                  <Space direction="vertical" style={{ width: '100%' }}>
                    <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>
                      {reviewOptionText(item.recommended_option)}
                    </Typography.Paragraph>
                    <Space wrap>
                      <Button
                        size="small"
                        type="primary"
                        onClick={() => chooseReviewOption(item, item.recommended_option)}
                        loading={applyReview.isPending}
                      >
                        Apply Recommended
                      </Button>
                      {item.alternative_candidates.map((candidate, candidateIndex) => (
                        <Button
                          key={candidateIndex}
                          size="small"
                          onClick={() => chooseReviewOption(item, candidate)}
                          loading={applyReview.isPending}
                        >
                          Apply Alternative {candidateIndex + 1}
                        </Button>
                      ))}
                    </Space>
                  </Space>
                }
              />
            ))}
          </Space>
        )}
      </Card>

      <Card title="Connectivity Result">
        {connectivitySummary ? (
          <Alert type="success" message="Connectivity Test Result" description={connectivitySummary} />
        ) : (
          <Empty description="尚未运行连通性测试" />
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
