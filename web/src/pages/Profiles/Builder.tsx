import { CheckCircleOutlined, FileSearchOutlined, PlayCircleOutlined } from '@ant-design/icons'
import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Descriptions,
  Empty,
  Form,
  Input,
  List,
  Row,
  Select,
  Space,
  Steps,
  Tag,
  Tooltip,
  Typography,
  Col,
} from 'antd'
import { useEffect, useState } from 'react'

import { useVLM } from '../../api/config'
import {
  useApplyProfileBuilderReview,
  useCaptureProfileBuilderStep,
  useCreateProfileBuilderSession,
  useGenerateProfileBuilderDraft,
  useValidateProfileBuilderDraft,
} from '../../api/profileBuilder'
import { useSaveProfile } from '../../api/profiles'
import {
  fetchProfileBuilderArtifactBlobUrl,
  useProfileBuilderRuntime,
} from '../../api/profileBuilderRuntime'
import { useDevices } from '../../api/devices'
import {
  Device,
  ProfileBuilderDraftResponse,
  ReviewEvidenceRef,
  ProfileBuilderRuntimeView,
  ProfileBuilderSessionView,
  ReviewItem,
} from '../../types/api'

const CAPTURE_STEPS = [
  {
    key: 'idle',
    title: 'Capture Idle State',
    description:
      '先手动发送一条测试消息并等待回复完成，停在真实对话页空闲态（输入框未聚焦、已有 assistant 气泡）后采集；同时会抓取响应气泡结构。',
  },
  {
    key: 'editing',
    title: 'Capture Editing State',
    description:
      '请先手动点开输入框并确认当前已经处于编辑态，然后再点击 Capture。Builder 只抓取你当前看到的编辑态屏幕，不会自动 tap 输入框，也不会在这个步骤临时切换输入法。ADB Keyboard 只会在 Start Builder Session 时开启一次，系统 toast 不保证会出现在 capture_editing.png 里。',
  },
] as const

function inferScreenStep(path: string): string {
  if (path.startsWith('capture_idle') || path.startsWith('capture_response')) {
    return 'idle'
  }
  if (path.startsWith('capture_editing')) {
    return 'editing'
  }
  if (path.startsWith('runtime_probe_') || path.startsWith('validate_')) {
    return 'connectivity'
  }
  return 'artifact'
}

function screenLabelFromPath(path: string): string {
  return path.replace(/\.[^.]+$/, '')
}

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
  if (Array.isArray(value)) {
    return value
      .map((step) => {
        if (step.action === 'tap_xy') {
          return `tap_xy: (${step.x}, ${step.y})`
        }
        if (step.action === 'click_locator' && step.locator) {
          return `click_locator: ${step.locator.type}: ${step.locator.value}`
        }
        return step.action
      })
      .join('\n')
  }
  if ('type' in value) {
    return `${value.type}: ${value.value}`
  }
  return [
    value.bubble_preview ? `bubble_text=${value.bubble_preview}` : null,
    `response=${value.response_container_locator.value}`,
    `scroll=${value.scroll_container_locator.value}`,
    `bubble=${value.latest_bubble_match.value}`,
  ]
    .filter(Boolean)
    .join('\n')
}

function toReviewPayload(
  field: string,
  value: ReviewItem['recommended_option'],
): Record<string, unknown> {
  if (Array.isArray(value)) {
    return { [field]: value }
  }
  if ('type' in value) {
    return { [field]: value }
  }
  return {
    response_extraction: {
      response_container_locator: value.response_container_locator,
      scroll_container_locator: value.scroll_container_locator,
      latest_bubble_match: value.resolved_latest_bubble_match ?? value.latest_bubble_match,
    },
  }
}

function normalizeBounds(bounds: ReviewEvidenceRef['bounds']): [number, number, number, number] | null {
  if (!bounds || bounds.length !== 4) {
    return null
  }
  return [Number(bounds[0]), Number(bounds[1]), Number(bounds[2]), Number(bounds[3])]
}

function collectAllEvidenceRefs(item: ReviewItem): ReviewEvidenceRef[] {
  return [item.evidence_refs, ...item.alternative_evidence_refs]
    .flat()
    .filter((ref): ref is ReviewEvidenceRef => Boolean(ref?.artifact))
}

export default function Builder() {
  const devices = useDevices()
  const createSession = useCreateProfileBuilderSession()
  const captureStep = useCaptureProfileBuilderStep()
  const generateDraft = useGenerateProfileBuilderDraft()
  const applyReview = useApplyProfileBuilderReview()
  const validateDraft = useValidateProfileBuilderDraft()
  const saveProfile = useSaveProfile()
  const { data: vlm } = useVLM()
  const { message } = App.useApp()

  const [selectedDevice, setSelectedDevice] = useState<string>()
  const [profileName, setProfileName] = useState('qwen_android')
  const [useLlmOptimization, setUseLlmOptimization] = useState(true)
  const [injectLlm, setInjectLlm] = useState(false)
  const [session, setSession] = useState<ProfileBuilderSessionView | null>(null)
  const [draft, setDraft] = useState<ProfileBuilderDraftResponse | null>(null)
  const [connectivitySummary, setConnectivitySummary] = useState<string | null>(null)
  const [currentScreenUrl, setCurrentScreenUrl] = useState<string | null>(null)
  const [selectedScreenPath, setSelectedScreenPath] = useState<string | null>(null)
  const [selectedStageKey, setSelectedStageKey] = useState<string | null>(null)
  const [followLatestScreen, setFollowLatestScreen] = useState(true)
  const [selectedEvidenceRefs, setSelectedEvidenceRefs] = useState<ReviewEvidenceRef[]>([])
  const [selectedEvidenceLabel, setSelectedEvidenceLabel] = useState<string | null>(null)
  const [imageNaturalSize, setImageNaturalSize] = useState<{ width: number; height: number } | null>(null)
  const [appliedReviewChoices, setAppliedReviewChoices] = useState<Record<string, string>>({})
  const runtime = useProfileBuilderRuntime(session?.id)
  const requiredReviewFields = draft ? Array.from(new Set(draft.review_items.map((item) => item.field))) : []
  const unresolvedReviewFields = requiredReviewFields.filter((field) => !appliedReviewChoices[field])
  const vlmReady = !!(vlm?.base_url && vlm?.model && vlm?.api_key)

  const onlineAndroidDevices = (devices.data ?? []).filter((device) => device.online && device.enabled)
  const completedSteps = new Set(
    session?.captures.filter((capture) => capture.active).map((capture) => capture.step) ?? [],
  )
  const runtimeData = runtime.data
  const sessionCaptureScreens =
    session?.captures
      .filter(
        (capture): capture is typeof capture & { screenshot_artifact: string } =>
          capture.screenshot_artifact != null,
      )
      .map((capture) => ({
        step: capture.step,
        label: capture.active ? `capture_${capture.step}` : `capture_${capture.step}_superseded`,
        path: capture.screenshot_artifact,
        taken_at: capture.captured_at ?? new Date(0).toISOString(),
      })) ?? []
  const sessionArtifactScreens =
    session?.artifacts
      .filter((artifact) => artifact.endsWith('.png'))
      .map((artifact) => ({
        step: inferScreenStep(artifact),
        label: screenLabelFromPath(artifact),
        path: artifact,
        taken_at: new Date(0).toISOString(),
      })) ?? []
  const captureScreens = runtimeData
    ? runtimeData.captures
        .filter(
          (capture): capture is typeof capture & { screenshot: string } => capture.screenshot != null,
        )
        .map((capture) => ({
          step: capture.step,
          label: `capture_${capture.step}`,
          path: capture.screenshot,
          taken_at: capture.updated_at ?? new Date(0).toISOString(),
        }))
    : []
  const availableScreens = [
    ...sessionCaptureScreens,
    ...sessionArtifactScreens,
    ...captureScreens,
    ...(runtimeData?.recent_screens ?? []),
    ...(runtimeData?.connectivity.screens ?? []),
  ].filter((screen, index, all) => all.findIndex((candidate) => candidate.path === screen.path) === index)
  const latestScreen = availableScreens[availableScreens.length - 1] ?? null
  const latestScreenForStage = (step: string | null) =>
    step != null ? availableScreens.filter((screen) => screen.step === step).slice(-1)[0] ?? null : null
  const selectedStageScreen = latestScreenForStage(selectedStageKey)
  const selectedEvidenceScreen =
    !followLatestScreen && selectedEvidenceRefs.length
      ? (() => {
          const target = selectedEvidenceRefs.find((ref) => ref.artifact === selectedScreenPath) ?? selectedEvidenceRefs[0]
          return target
            ? {
                step: target.step,
                label: target.label ?? screenLabelFromPath(target.artifact),
                path: target.artifact,
                taken_at: new Date(0).toISOString(),
              }
            : null
        })()
      : null
  const currentScreen =
    (followLatestScreen
      ? latestScreen
      : availableScreens.find((screen) => screen.path === selectedScreenPath) ??
        selectedEvidenceScreen ??
        selectedStageScreen) ??
    null
  const visibleEvidenceRefs = selectedEvidenceRefs.filter(
    (ref) => currentScreen != null && ref.artifact === currentScreen.path && normalizeBounds(ref.bounds),
  )

  useEffect(() => {
    if (!latestScreen) {
      setSelectedScreenPath(null)
      setSelectedStageKey(null)
      return
    }
    if (followLatestScreen || (!selectedScreenPath && !selectedStageKey)) {
      setSelectedScreenPath(latestScreen.path)
      setSelectedStageKey(latestScreen.step)
    }
  }, [followLatestScreen, latestScreen, selectedScreenPath, selectedStageKey])

  useEffect(() => {
    setImageNaturalSize(null)
  }, [currentScreen?.path])

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
    const confirmed = window.confirm(
      '开始前请确认：\n1. 目标 App 中已经手动发送过一条测试消息，并停留在真实对话页。\n2. 接下来会保持 ADB Keyboard 开启，直到点击 Generate Draft。',
    )
    if (!confirmed) {
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
      setSelectedStageKey(null)
      setFollowLatestScreen(true)
      setSelectedEvidenceRefs([])
      setSelectedEvidenceLabel(null)
      setAppliedReviewChoices({})
      setUseLlmOptimization(true)
      setInjectLlm(false)
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
      setSelectedEvidenceRefs([])
      setSelectedEvidenceLabel(null)
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
      const nextDraft = await generateDraft.mutateAsync({
        sessionId: session.id,
        useLlmOptimization,
        injectLlm,
      })
      setSession(nextDraft.session)
      setDraft(nextDraft)
      setConnectivitySummary(null)
      setSelectedEvidenceRefs([])
      setSelectedEvidenceLabel(null)
      setAppliedReviewChoices({})
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
      })
      setAppliedReviewChoices((previous) => ({
        ...previous,
        [item.field]: reviewOptionText(option),
      }))
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
      setSelectedEvidenceRefs([])
      setSelectedEvidenceLabel(null)
      message.success('Connectivity test 已完成')
    } catch (error) {
      message.error((error as Error).message)
    }
  }

  const focusEvidence = (refs: ReviewEvidenceRef[], label: string) => {
    const target = refs.find((ref) => ref.artifact)
    if (!target) {
      return
    }
    setFollowLatestScreen(false)
    setSelectedStageKey(target.step)
    setSelectedScreenPath(target.artifact)
    setSelectedEvidenceRefs(refs)
    setSelectedEvidenceLabel(label)
  }

  const saveDraftAsProfile = async () => {
    if (!draft) {
      return
    }
    const name = profileName.trim() || session?.name.trim()
    if (!name) {
      message.warning('请先填写 Profile Name')
      return
    }
    try {
      await saveProfile.mutateAsync({
        name,
        yaml: draft.draft_profile_yaml,
        create: true,
      })
      message.success(`已保存到 Profiles: ${name}`)
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
              disabled={!draft || unresolvedReviewFields.length > 0}
              icon={<CheckCircleOutlined />}
              loading={validateDraft.isPending}
              onClick={runConnectivityValidation}
            >
              Run Connectivity Test
            </Button>
          </Space>
          {unresolvedReviewFields.length ? (
            <Alert
              style={{ marginTop: 12 }}
              type="warning"
              showIcon
              message="请先确认关键 Review Items"
              description={`未确认字段: ${unresolvedReviewFields.join(', ')}`}
            />
          ) : null}
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
                {session?.captures.filter((capture) => capture.step === step.key).length ? (
                  <Space direction="vertical" size={4} style={{ width: '100%' }}>
                    {session.captures
                      .filter((capture) => capture.step === step.key)
                      .map((capture) => (
                        <Space key={`${capture.step}-${capture.xml_artifact}`} size="small" wrap>
                          <Tag color={capture.active ? 'blue' : 'default'}>
                            {capture.active ? 'Active' : 'Superseded'}
                          </Tag>
                          <Typography.Text type="secondary">
                            {capture.screenshot_artifact}
                          </Typography.Text>
                          {capture.captured_at ? (
                            <Typography.Text type="secondary">
                              {new Date(capture.captured_at).toLocaleString()}
                            </Typography.Text>
                          ) : null}
                        </Space>
                      ))}
                  </Space>
                ) : null}
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
        <div style={{ marginTop: 12 }}>
          <Tooltip title={vlmReady ? '' : '先在 Config 页面配置完整 VLM 凭据'}>
            <Checkbox
              checked={useLlmOptimization}
              disabled={!vlmReady}
              onChange={(event) => setUseLlmOptimization(event.target.checked)}
              aria-label="生成 Draft 时使用 LLM 优化"
            >
              生成 Draft 时使用 LLM 优化
            </Checkbox>
          </Tooltip>
        </div>
        <div style={{ marginTop: 8 }}>
          <Tooltip title={vlmReady ? '' : '先在 Config 页面配置完整 VLM 凭据'}>
            <Checkbox
              checked={injectLlm}
              disabled={!vlmReady}
              onChange={(event) => setInjectLlm(event.target.checked)}
              aria-label="生成时注入 LLM 响应抽取配置"
            >
              生成时注入 LLM 响应抽取配置
            </Checkbox>
          </Tooltip>
        </div>
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
                        title: (
                          <Button
                            type="text"
                            style={{
                              paddingInline: 0,
                              fontWeight: selectedStageKey === step.key ? 600 : undefined,
                            }}
                            onClick={() => {
                              setFollowLatestScreen(false)
                              setSelectedStageKey(step.key)
                              setSelectedScreenPath(latestScreenForStage(step.key)?.path ?? null)
                              setSelectedEvidenceRefs([])
                              setSelectedEvidenceLabel(null)
                            }}
                          >
                            {step.title}
                          </Button>
                        ),
                        status: runtimeStepStatus(runtimeData, step.key),
                      })),
                      {
                        title: (
                          <Button
                            type="text"
                            style={{
                              paddingInline: 0,
                              fontWeight: selectedStageKey === 'draft' ? 600 : undefined,
                            }}
                            onClick={() => {
                              setFollowLatestScreen(false)
                              setSelectedStageKey('draft')
                              setSelectedScreenPath(null)
                              setSelectedEvidenceRefs([])
                              setSelectedEvidenceLabel(null)
                            }}
                          >
                            Generate Draft
                          </Button>
                        ),
                        status: runtimeStepStatus(runtimeData, 'draft'),
                      },
                      {
                        title: (
                          <Button
                            type="text"
                            style={{
                              paddingInline: 0,
                              fontWeight: selectedStageKey === 'connectivity' ? 600 : undefined,
                            }}
                            onClick={() => {
                              setFollowLatestScreen(false)
                              setSelectedStageKey('connectivity')
                              setSelectedScreenPath(latestScreenForStage('connectivity')?.path ?? null)
                              setSelectedEvidenceRefs([])
                              setSelectedEvidenceLabel(null)
                            }}
                          >
                            Run Connectivity Test
                          </Button>
                        ),
                        status: runtimeStepStatus(runtimeData, 'connectivity'),
                      },
                    ]}
                  />
                </Space>
              ) : (
                <Empty description="启动 session 后自动显示运行状态" />
              )}
            </Card>
            <Card title="Review Items" style={{ marginTop: 16 }}>
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
                          {appliedReviewChoices[item.field] ? (
                            <Alert
                              type="success"
                              showIcon
                              message="当前已应用"
                              description={
                                <Typography.Text style={{ whiteSpace: 'pre-wrap' }}>
                                  {appliedReviewChoices[item.field]}
                                </Typography.Text>
                              }
                            />
                          ) : null}
                          <Space wrap>
                            <Button
                              size="small"
                              type="primary"
                              onClick={() => chooseReviewOption(item, item.recommended_option)}
                              loading={applyReview.isPending}
                            >
                              Apply Recommended
                            </Button>
                            <Button
                              size="small"
                              onClick={() => focusEvidence(item.evidence_refs, `${item.field} · 推荐定位`)}
                              disabled={!item.evidence_refs.length}
                            >
                              查看推荐定位
                            </Button>
                            <Button
                              size="small"
                              onClick={() =>
                                focusEvidence(
                                  collectAllEvidenceRefs(item),
                                  `${item.field} · 全部证据`,
                                )
                              }
                              disabled={!collectAllEvidenceRefs(item).length}
                            >
                              查看全部证据
                            </Button>
                            {item.alternative_candidates.map((candidate, candidateIndex) => (
                              <Space key={candidateIndex} size="small">
                                <Button
                                  size="small"
                                  onClick={() => chooseReviewOption(item, candidate)}
                                  loading={applyReview.isPending}
                                >
                                  Apply Alternative {candidateIndex + 1}
                                </Button>
                                <Button
                                  size="small"
                                  onClick={() =>
                                    focusEvidence(
                                      item.alternative_evidence_refs[candidateIndex] ?? [],
                                      `${item.field} · 备选 ${candidateIndex + 1}`,
                                    )
                                  }
                                  disabled={!(item.alternative_evidence_refs[candidateIndex] ?? []).length}
                                >
                                  查看备选 {candidateIndex + 1}
                                </Button>
                              </Space>
                            ))}
                          </Space>
                        </Space>
                      }
                    />
                  ))}
                </Space>
              )}
            </Card>
            <Card title="Connectivity Result" style={{ marginTop: 16 }}>
              {connectivitySummary ? (
                <Alert type="success" message="Connectivity Test Result" description={connectivitySummary} />
              ) : (
                <Empty description="尚未运行连通性测试" />
              )}
            </Card>
            <Card
              title="Draft YAML"
              style={{ marginTop: 16 }}
              extra={
                <Button
                  type="primary"
                  disabled={!draft}
                  loading={saveProfile.isPending}
                  onClick={saveDraftAsProfile}
                >
                  保存/覆盖到 Profiles
                </Button>
              }
            >
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
          </Col>
          <Col xs={24} lg={10}>
            <Card
              title="Key Screens"
              loading={runtime.isLoading && !runtimeData}
              style={{
                position: 'sticky',
                top: 16,
                maxHeight: 'calc(100vh - 32px)',
                overflowY: 'auto',
              }}
            >
              {!runtimeData ? (
                <Empty description="暂无关键截图" />
              ) : (
                <Space direction="vertical" style={{ width: '100%' }} size="middle">
                  {currentScreen ? (
                    <>
                      <Typography.Text strong>{currentScreen.label}</Typography.Text>
                      {selectedEvidenceLabel ? (
                        <Typography.Text type="secondary">{selectedEvidenceLabel}</Typography.Text>
                      ) : null}
                      {currentScreenUrl ? (
                        <div style={{ position: 'relative', width: '100%' }}>
                          <img
                            src={currentScreenUrl}
                            alt={currentScreen.label}
                            style={{ width: '100%', display: 'block', borderRadius: 8 }}
                            onLoad={(event) => {
                              const img = event.currentTarget
                              setImageNaturalSize({
                                width: img.naturalWidth,
                                height: img.naturalHeight,
                              })
                            }}
                          />
                          {imageNaturalSize
                            ? visibleEvidenceRefs.map((ref, index) => {
                                const bounds = normalizeBounds(ref.bounds)
                                if (!bounds) {
                                  return null
                                }
                                const [x1, y1, x2, y2] = bounds
                                return (
                                  <div
                                    key={`${ref.artifact}-${index}`}
                                    style={{
                                      position: 'absolute',
                                      left: `${(x1 / imageNaturalSize.width) * 100}%`,
                                      top: `${(y1 / imageNaturalSize.height) * 100}%`,
                                      width: `${((x2 - x1) / imageNaturalSize.width) * 100}%`,
                                      height: `${((y2 - y1) / imageNaturalSize.height) * 100}%`,
                                      border: `2px solid ${index === 0 ? '#1677ff' : '#fa8c16'}`,
                                      background: index === 0 ? 'rgba(22, 119, 255, 0.12)' : 'rgba(250, 140, 22, 0.12)',
                                      borderRadius: 6,
                                      pointerEvents: 'none',
                                    }}
                                  />
                                )
                              })
                            : null}
                        </div>
                      ) : (
                        <Alert type="warning" showIcon message="截图加载失败" />
                      )}
                    </>
                  ) : null}
                  {!currentScreen ? (
                    <Empty
                      description={
                        selectedStageKey
                          ? `当前阶段 ${selectedStageKey} 暂无截图`
                          : '暂无关键截图'
                      }
                    />
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
                          setSelectedStageKey(latestScreen.step)
                        }
                        setSelectedEvidenceRefs([])
                        setSelectedEvidenceLabel(null)
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
                          setSelectedStageKey(item.step)
                          setSelectedScreenPath(item.path)
                          setSelectedEvidenceRefs([])
                          setSelectedEvidenceLabel(null)
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

    </Space>
  )
}
