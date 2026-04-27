import {
  CheckCircleOutlined,
  DownOutlined,
  FileSearchOutlined,
  PlayCircleOutlined,
  UpOutlined,
} from '@ant-design/icons'
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
  Radio,
  Row,
  Select,
  Space,
  Steps,
  Tag,
  Tooltip,
  Typography,
  Col,
} from 'antd'
import { useEffect, useMemo, useState } from 'react'

import { useVLM } from '../../api/config'
import {
  useApplyProfileBuilderReview,
  useCaptureProfileBuilderStep,
  useCaptureProfileBuilderNewSessionStep,
  useConfigureProfileBuilderNewSession,
  useConfirmProfileBuilderNewSessionStep,
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
import { ResponseComparison } from '../../components/ResponseComparison'
import {
  Device,
  ProfileBuilderDraftResponse,
  ProfileBuilderNewSessionStep,
  ReviewEvidenceRef,
  SingleTestSyncResponse,
  ProfileBuilderRuntimeView,
  ProfileBuilderSessionView,
  ReviewItem,
} from '../../types/api'
import { hasLLMExtractionData } from '../../utils/llmExtraction'

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

function reviewOptionByIndex(item: ReviewItem, index: number): ReviewItem['recommended_option'] | null {
  const options = [item.recommended_option, ...item.alternative_candidates]
  return options[index] ?? null
}

function appliedChoiceLabelsFromDraft(
  nextDraft: ProfileBuilderDraftResponse,
): Record<string, string> {
  return Object.fromEntries(
    Object.entries(nextDraft.applied_review_choices).flatMap(([field, index]) => {
      const item = nextDraft.review_items.find((candidate) => candidate.field === field)
      const option = item ? reviewOptionByIndex(item, index) : null
      return option ? [[field, reviewOptionText(option)]] : []
    }),
  )
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

function reviewItemKey(item: ReviewItem, index: number): string {
  return `${item.field}-${index}`
}

function formatRecommendationError(error: string | null | undefined): string {
  switch (error) {
    case 'vlm_unavailable':
      return 'VLM 未配置'
    case 'auth_error':
      return '认证失败'
    case 'connect_error':
      return '连接失败'
    case 'image_input_unsupported':
      return '模型不支持图像输入'
    case 'structured_output_unsupported':
      return '模型不支持结构化输出'
    case 'model_error':
      return '模型不可用'
    case 'request_invalid':
      return '请求参数无效'
    case 'response_shape_error':
      return '返回格式异常'
    default:
      return error || '未知错误'
  }
}

function newSessionRecommendationMessage(step: ProfileBuilderNewSessionStep): string {
  const { recommended_tap: recommendedTap } = step
  switch (recommendedTap.status) {
    case 'ready':
      if (!recommendedTap.point) {
        return '推荐结果缺少坐标，请人工点选'
      }
      return [
        `推荐点: (${recommendedTap.point.x}, ${recommendedTap.point.y})`,
        recommendedTap.reason ? `原因: ${recommendedTap.reason}` : null,
      ]
        .filter(Boolean)
        .join(' | ')
    case 'unavailable':
      return '当前未配置 VLM，仅支持人工点选'
    case 'failed':
      return `推荐请求失败：${formatRecommendationError(recommendedTap.error)}`
    case 'idle':
    default:
      return '暂无推荐，请先 Capture 或人工点选'
  }
}

function newSessionRecommendationAlertType(
  status: ProfileBuilderNewSessionStep['recommended_tap']['status'],
): 'info' | 'success' | 'warning' {
  if (status === 'ready') {
    return 'success'
  }
  if (status === 'failed' || status === 'unavailable') {
    return 'warning'
  }
  return 'info'
}

export default function Builder() {
  const devices = useDevices()
  const createSession = useCreateProfileBuilderSession()
  const captureStep = useCaptureProfileBuilderStep()
  const generateDraft = useGenerateProfileBuilderDraft()
  const applyReview = useApplyProfileBuilderReview()
  const validateDraft = useValidateProfileBuilderDraft()
  const configureNewSession = useConfigureProfileBuilderNewSession()
  const captureNewSessionStep = useCaptureProfileBuilderNewSessionStep()
  const confirmNewSessionStep = useConfirmProfileBuilderNewSessionStep()
  const saveProfile = useSaveProfile()
  const { data: vlm } = useVLM()
  const { message } = App.useApp()

  const [selectedDevice, setSelectedDevice] = useState<string>()
  const [profileName, setProfileName] = useState('qwen_android')
  const [draftMode, setDraftMode] = useState<'rule' | 'smart'>('smart')
  const [injectLlm, setInjectLlm] = useState(false)
  const [session, setSession] = useState<ProfileBuilderSessionView | null>(null)
  const [draft, setDraft] = useState<ProfileBuilderDraftResponse | null>(null)
  const [connectivityResult, setConnectivityResult] = useState<SingleTestSyncResponse | null>(null)
  const [currentScreenUrl, setCurrentScreenUrl] = useState<string | null>(null)
  const [selectedScreenPath, setSelectedScreenPath] = useState<string | null>(null)
  const [selectedStageKey, setSelectedStageKey] = useState<string | null>(null)
  const [followLatestScreen, setFollowLatestScreen] = useState(true)
  const [selectedEvidenceRefs, setSelectedEvidenceRefs] = useState<ReviewEvidenceRef[]>([])
  const [selectedEvidenceLabel, setSelectedEvidenceLabel] = useState<string | null>(null)
  const [imageNaturalSize, setImageNaturalSize] = useState<{ width: number; height: number } | null>(null)
  const [newSessionStepPreviewUrls, setNewSessionStepPreviewUrls] = useState<Record<string, string>>(
    {},
  )
  const [newSessionStepPreviewSizes, setNewSessionStepPreviewSizes] = useState<
    Record<string, { width: number; height: number }>
  >({})
  const [expandedNewSessionPreviews, setExpandedNewSessionPreviews] = useState<Record<number, boolean>>({})
  const [appliedReviewChoices, setAppliedReviewChoices] = useState<Record<string, string>>({})
  const [expandedReviewItems, setExpandedReviewItems] = useState<Record<string, boolean>>({})
  const [activeReviewKey, setActiveReviewKey] = useState<string | null>(null)
  const [showUnresolvedOnly, setShowUnresolvedOnly] = useState(false)
  const [newSessionStrategy, setNewSessionStrategy] = useState<'disabled' | 'guided_tap_sequence'>('disabled')
  const [newSessionStepCount, setNewSessionStepCount] = useState(1)
  const [manualTapStepIndex, setManualTapStepIndex] = useState<number | null>(null)
  const runtime = useProfileBuilderRuntime(session?.id)
  const reviewEntries = useMemo(
    () => draft?.review_items.map((item, index) => ({ item, index, key: reviewItemKey(item, index) })) ?? [],
    [draft],
  )
  const requiredReviewFields = draft ? Array.from(new Set(draft.review_items.map((item) => item.field))) : []
  const unresolvedReviewFields = draft?.pending_review_fields ?? requiredReviewFields.filter((field) => !appliedReviewChoices[field])
  const unresolvedFieldSet = useMemo(() => new Set(unresolvedReviewFields), [unresolvedReviewFields])
  const filteredReviewEntries = reviewEntries.filter(
    ({ item }) => !showUnresolvedOnly || unresolvedFieldSet.has(item.field),
  )
  const activeReviewEntry =
    filteredReviewEntries.find((entry) => entry.key === activeReviewKey) ??
    reviewEntries.find((entry) => entry.key === activeReviewKey) ??
    null
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
  const relatedEvidenceRefs = activeReviewEntry ? collectAllEvidenceRefs(activeReviewEntry.item) : []
  const relatedEvidenceScreens = relatedEvidenceRefs
    .map((ref) => ({
      step: ref.step,
      label: ref.label ?? screenLabelFromPath(ref.artifact),
      path: ref.artifact,
      taken_at:
        availableScreens.find((screen) => screen.path === ref.artifact)?.taken_at ?? new Date(0).toISOString(),
    }))
    .filter((screen, index, all) => all.findIndex((candidate) => candidate.path === screen.path) === index)
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
    let cancelled = false
    let loadedUrls: string[] = []

    const revokeObjectUrl = (value: string) => {
      if (typeof URL.revokeObjectURL === 'function') {
        URL.revokeObjectURL(value)
      }
    }

    async function loadStepPreviews() {
      if (!session?.id) {
        setNewSessionStepPreviewUrls({})
        return
      }
      const stepArtifacts = (draft?.new_session_steps ?? [])
        .map((step) => step.screenshot_artifact)
        .filter((artifact): artifact is string => Boolean(artifact))
      if (!stepArtifacts.length) {
        setNewSessionStepPreviewUrls({})
        return
      }
      try {
        const entries = await Promise.all(
          stepArtifacts.map(async (artifact) => [artifact, await fetchProfileBuilderArtifactBlobUrl(session.id, artifact)] as const),
        )
        loadedUrls = entries.map(([, url]) => url)
        if (cancelled) {
          entries.forEach(([, url]) => revokeObjectUrl(url))
          return
        }
        setNewSessionStepPreviewUrls((previous) => {
          Object.values(previous).forEach(revokeObjectUrl)
          return Object.fromEntries(entries)
        })
      } catch {
        if (!cancelled) {
          setNewSessionStepPreviewUrls({})
        }
      }
    }

    void loadStepPreviews()

    return () => {
      cancelled = true
      loadedUrls.forEach(revokeObjectUrl)
    }
  }, [draft?.new_session_steps, session?.id])

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
      setConnectivityResult(null)
      setCurrentScreenUrl(null)
      setSelectedScreenPath(null)
      setSelectedStageKey(null)
      setFollowLatestScreen(true)
      setSelectedEvidenceRefs([])
      setSelectedEvidenceLabel(null)
      setAppliedReviewChoices({})
      setExpandedReviewItems({})
      setActiveReviewKey(null)
      setShowUnresolvedOnly(false)
      setDraftMode(vlmReady ? 'smart' : 'rule')
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
      setConnectivityResult(null)
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
        draftMode,
        injectLlm,
      })
      setSession(nextDraft.session)
      setDraft(nextDraft)
      setConnectivityResult(null)
      setSelectedEvidenceRefs([])
      setSelectedEvidenceLabel(null)
      setAppliedReviewChoices(appliedChoiceLabelsFromDraft(nextDraft))
      setExpandedReviewItems({})
      setShowUnresolvedOnly(false)
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
        pending_review_fields: draft.pending_review_fields.filter((field) => field !== item.field),
        requires_manual_review: draft.pending_review_fields.filter((field) => field !== item.field).length > 0,
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

  const handleNewSessionStrategyChange = async (strategy: 'disabled' | 'guided_tap_sequence') => {
    setNewSessionStrategy(strategy)
    if (!session) return
    try {
      const result = await configureNewSession.mutateAsync({ sessionId: session.id, strategy, stepCount: newSessionStepCount })
      setDraft(result)
      setManualTapStepIndex(null)
      setExpandedNewSessionPreviews({})
    } catch (error) {
      message.error((error as Error).message)
    }
  }

  const handleNewSessionStepCountChange = async (stepCount: number) => {
    setNewSessionStepCount(stepCount)
    if (!session || newSessionStrategy !== 'guided_tap_sequence') return
    try {
      const result = await configureNewSession.mutateAsync({ sessionId: session.id, strategy: 'guided_tap_sequence', stepCount })
      setDraft(result)
      setManualTapStepIndex(null)
      setExpandedNewSessionPreviews((current) =>
        Object.fromEntries(
          Object.entries(current).filter(([key]) => Number(key) < stepCount),
        ),
      )
    } catch (error) {
      message.error((error as Error).message)
    }
  }

  const handleNewSessionStepCapture = async (stepIndex: number) => {
    if (!session) return
    try {
      const result = await captureNewSessionStep.mutateAsync({ sessionId: session.id, stepIndex })
      setDraft(result)
      setExpandedNewSessionPreviews((current) => ({ ...current, [stepIndex]: true }))
    } catch (error) {
      message.error((error as Error).message)
    }
  }

  const handleAcceptRecommendedTap = async (step: ProfileBuilderNewSessionStep) => {
    if (!session || step.recommended_tap.status !== 'ready' || !step.recommended_tap.point) return
    try {
      const result = await confirmNewSessionStep.mutateAsync({
        sessionId: session.id,
        stepIndex: step.step_index,
        x: step.recommended_tap.point.x,
        y: step.recommended_tap.point.y,
        source: 'recommended',
      })
      setDraft(result as ProfileBuilderDraftResponse)
      setManualTapStepIndex(null)
      setExpandedNewSessionPreviews((current) => ({ ...current, [step.step_index]: false }))
    } catch (error) {
      message.error((error as Error).message)
    }
  }

  const handleNewSessionStepImageClick = async (
    event: React.MouseEvent<HTMLDivElement>,
    stepIndex: number,
    screenshotArtifact: string | null,
  ) => {
    if (!session) return
    const rect = event.currentTarget.getBoundingClientRect()
    const naturalSize = screenshotArtifact ? newSessionStepPreviewSizes[screenshotArtifact] : undefined
    const scaleX = rect.width > 0 && naturalSize ? naturalSize.width / rect.width : 1
    const scaleY = rect.height > 0 && naturalSize ? naturalSize.height / rect.height : 1
    const x = Math.round((event.clientX - rect.left) * scaleX)
    const y = Math.round((event.clientY - rect.top) * scaleY)
    try {
      const result = await confirmNewSessionStep.mutateAsync({ sessionId: session.id, stepIndex, x, y, source: 'manual' })
      setDraft(result as ProfileBuilderDraftResponse)
      setManualTapStepIndex(null)
      setExpandedNewSessionPreviews((current) => ({ ...current, [stepIndex]: false }))
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
      setConnectivityResult(validated.connectivity_result)
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

  const toggleReviewItem = (key: string) => {
    setExpandedReviewItems((previous) => ({
      ...previous,
      [key]: !previous[key],
    }))
  }

  const focusReviewItem = (item: ReviewItem, key: string, expand = false) => {
    setActiveReviewKey(key)
    if (expand) {
      setExpandedReviewItems((previous) => ({ ...previous, [key]: true }))
    }
    if (!collectAllEvidenceRefs(item).length) {
      setSelectedEvidenceRefs([])
      setSelectedEvidenceLabel(null)
      return
    }
    const recommendedRefs = item.evidence_refs.length ? item.evidence_refs : collectAllEvidenceRefs(item)
    const target = recommendedRefs[0]
    setFollowLatestScreen(false)
    setSelectedStageKey(target.step)
    setSelectedScreenPath(target.artifact)
    setSelectedEvidenceRefs(recommendedRefs)
    setSelectedEvidenceLabel(`${item.field} · 推荐定位`)
  }

  useEffect(() => {
    if (!reviewEntries.length) {
      setActiveReviewKey(null)
      return
    }
    const activeStillExists = activeReviewKey && reviewEntries.some((entry) => entry.key === activeReviewKey)
    if (activeStillExists) {
      return
    }
    const nextActive =
      reviewEntries.find(({ item }) => unresolvedFieldSet.has(item.field))?.key ?? reviewEntries[0]?.key ?? null
    setActiveReviewKey(nextActive)
  }, [activeReviewKey, reviewEntries, unresolvedFieldSet])

  useEffect(() => {
    if (!activeReviewEntry) {
      return
    }
    const refs = collectAllEvidenceRefs(activeReviewEntry.item)
    if (refs.length) {
      const recommendedRefs =
        activeReviewEntry.item.evidence_refs.length ? activeReviewEntry.item.evidence_refs : refs
      const target = recommendedRefs[0]
      setFollowLatestScreen(false)
      setSelectedStageKey(target.step)
      setSelectedScreenPath(target.artifact)
      setSelectedEvidenceRefs(recommendedRefs)
      setSelectedEvidenceLabel(`${activeReviewEntry.item.field} · 推荐定位`)
    }
  }, [activeReviewEntry])

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
              disabled={!draft || draft.requires_manual_review}
              icon={<CheckCircleOutlined />}
              loading={validateDraft.isPending}
              onClick={runConnectivityValidation}
            >
              Run Connectivity Test
            </Button>
          </Space>
          {draft?.requires_manual_review && unresolvedReviewFields.length ? (
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
          <Typography.Text strong>Draft Mode</Typography.Text>
          <div style={{ marginTop: 8 }}>
            <Radio.Group
              value={draftMode}
              onChange={(event) => setDraftMode(event.target.value)}
            >
              <Space direction="vertical">
                <Radio value="rule" aria-label="规则 Draft（需人工确认 Review）">
                  规则 Draft（需人工确认 Review）
                </Radio>
                <Tooltip title={vlmReady ? '' : '先在 Config 页面配置完整 VLM 凭据'}>
                  <Radio
                    value="smart"
                    disabled={!vlmReady}
                    aria-label="智能 Draft（LLM 自动选择 Review）"
                  >
                    智能 Draft（LLM 自动选择 Review）
                  </Radio>
                </Tooltip>
              </Space>
            </Radio.Group>
          </div>
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

      <Card title="New Session Action" style={{ marginTop: 16 }}>
        <Space direction="vertical" style={{ width: '100%' }}>
          <Radio.Group
            value={newSessionStrategy}
            onChange={(event) => void handleNewSessionStrategyChange(event.target.value as 'disabled' | 'guided_tap_sequence')}
          >
            <Space direction="vertical">
              <Radio value="disabled">不配置</Radio>
              <Radio value="guided_tap_sequence" aria-label="配置多步新开对话">
                配置多步新开对话
              </Radio>
            </Space>
          </Radio.Group>
          <div>
            <Typography.Text type="secondary">Step Count</Typography.Text>
            <Radio.Group
              style={{ marginLeft: 8 }}
              value={newSessionStepCount}
              onChange={(event) => void handleNewSessionStepCountChange(event.target.value as number)}
              disabled={newSessionStrategy === 'disabled'}
            >
              {[1, 2, 3].map((n) => (
                <Radio key={n} value={n} aria-label={`Step Count ${n}`}>{n}</Radio>
              ))}
            </Radio.Group>
          </div>
          {(draft?.new_session_steps ?? []).map((step) => (
            <Card
              key={step.step_index}
              size="small"
              title={`New Session Step ${step.step_index + 1}`}
              extra={(
                <Space size="small">
                  {step.screenshot_artifact ? (
                    <Button
                      size="small"
                      type="text"
                      onClick={() =>
                        setExpandedNewSessionPreviews((current) => ({
                          ...current,
                          [step.step_index]: !current[step.step_index],
                        }))}
                    >
                      {expandedNewSessionPreviews[step.step_index] ? '收回图片' : '展开图片'}
                    </Button>
                  ) : null}
                  {step.confirmed_tap ? <Tag color="green">已确认</Tag> : <Tag>待确认</Tag>}
                </Space>
              )}
            >
              <Space direction="vertical" style={{ width: '100%' }}>
                <Space>
                  <Button
                    size="small"
                    onClick={() => void handleNewSessionStepCapture(step.step_index)}
                    loading={captureNewSessionStep.isPending}
                    disabled={!session}
                  >
                    Capture
                  </Button>
                  <Button
                    size="small"
                    disabled={step.recommended_tap.status !== 'ready' || !step.recommended_tap.point}
                    onClick={() => void handleAcceptRecommendedTap(step)}
                  >
                    接受推荐
                  </Button>
                  <Button
                    size="small"
                    onClick={() => {
                      const nextManualTapStepIndex =
                        manualTapStepIndex === step.step_index ? null : step.step_index
                      setManualTapStepIndex(nextManualTapStepIndex)
                      if (nextManualTapStepIndex !== null) {
                        setExpandedNewSessionPreviews((current) => ({
                          ...current,
                          [step.step_index]: true,
                        }))
                      }
                    }}
                    disabled={!step.screenshot_artifact}
                  >
                    {manualTapStepIndex === step.step_index ? '取消点选' : '重新点选'}
                  </Button>
                </Space>
                <Alert
                  type={newSessionRecommendationAlertType(step.recommended_tap.status)}
                  showIcon
                  message={newSessionRecommendationMessage(step)}
                />
                {step.confirmed_tap && (
                  <Tag color="blue">
                    已选: ({step.confirmed_tap.x}, {step.confirmed_tap.y}) [{step.source}]
                  </Tag>
                )}
                {manualTapStepIndex === step.step_index && (
                  <Typography.Text type="warning">点击下方截图选择 tap 点</Typography.Text>
                )}
                {step.screenshot_artifact && expandedNewSessionPreviews[step.step_index] && (
                  <div
                    aria-label={`New Session Step ${step.step_index + 1} preview`}
                    style={{
                      cursor: manualTapStepIndex === step.step_index ? 'crosshair' : 'default',
                      display: 'inline-block',
                      position: 'relative',
                    }}
                    onClick={(event) => {
                      if (manualTapStepIndex !== step.step_index) return
                      void handleNewSessionStepImageClick(
                        event,
                        step.step_index,
                        step.screenshot_artifact,
                      )
                    }}
                  >
                    <img
                      src={newSessionStepPreviewUrls[step.screenshot_artifact] ?? undefined}
                      alt={`step ${step.step_index + 1} screenshot`}
                      style={{ maxWidth: '100%', display: 'block' }}
                      onLoad={(event) => {
                        const img = event.currentTarget
                        const artifact = step.screenshot_artifact
                        if (!artifact) return
                        setNewSessionStepPreviewSizes((current) => ({
                          ...current,
                          [artifact]: {
                            width: img.naturalWidth,
                            height: img.naturalHeight,
                          },
                        }))
                      }}
                    />
                    {step.screenshot_artifact && newSessionStepPreviewSizes[step.screenshot_artifact]
                      ? (
                          <>
                            {step.recommended_tap.point ? (
                              <div
                                aria-label={`New Session Step ${step.step_index + 1} recommended point`}
                                style={{
                                  position: 'absolute',
                                  left: `${(step.recommended_tap.point.x / newSessionStepPreviewSizes[step.screenshot_artifact].width) * 100}%`,
                                  top: `${(step.recommended_tap.point.y / newSessionStepPreviewSizes[step.screenshot_artifact].height) * 100}%`,
                                  width: 18,
                                  height: 18,
                                  transform: 'translate(-50%, -50%)',
                                  border: '2px solid #fa8c16',
                                  background: 'rgba(250, 140, 22, 0.18)',
                                  borderRadius: 6,
                                  boxShadow: '0 0 0 2px rgba(255,255,255,0.9)',
                                  pointerEvents: 'none',
                                }}
                              />
                            ) : null}
                            {step.confirmed_tap ? (
                              <div
                                aria-label={`New Session Step ${step.step_index + 1} confirmed point`}
                                style={{
                                  position: 'absolute',
                                  left: `${(step.confirmed_tap.x / newSessionStepPreviewSizes[step.screenshot_artifact].width) * 100}%`,
                                  top: `${(step.confirmed_tap.y / newSessionStepPreviewSizes[step.screenshot_artifact].height) * 100}%`,
                                  width: 20,
                                  height: 20,
                                  transform: 'translate(-50%, -50%)',
                                  border: '2px solid #1677ff',
                                  background: 'rgba(22, 119, 255, 0.18)',
                                  borderRadius: '50%',
                                  boxShadow: '0 0 0 2px rgba(255,255,255,0.95)',
                                  pointerEvents: 'none',
                                }}
                              />
                            ) : null}
                          </>
                        )
                      : null}
                  </div>
                )}
              </Space>
            </Card>
          ))}
        </Space>
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
                  <Space style={{ width: '100%', justifyContent: 'space-between' }} wrap>
                    <Space wrap>
                      <Checkbox
                        checked={showUnresolvedOnly}
                        onChange={(event) => setShowUnresolvedOnly(event.target.checked)}
                        aria-label="仅看未完成"
                      >
                        仅看未完成
                      </Checkbox>
                      <Button
                        size="small"
                        onClick={() => setExpandedReviewItems({})}
                        disabled={!Object.values(expandedReviewItems).some(Boolean)}
                      >
                        全部收起
                      </Button>
                    </Space>
                    <Typography.Text type="secondary">
                      {unresolvedReviewFields.length} / {reviewEntries.length} 未完成
                    </Typography.Text>
                  </Space>
                  {!filteredReviewEntries.length ? (
                    <Empty description="当前筛选下没有待处理 Review Items" />
                  ) : null}
                  {filteredReviewEntries.map(({ item, key }) => (
                    (() => {
                      const expanded = !!expandedReviewItems[key]
                      const isActive = activeReviewKey === key
                      const isApplied = !!appliedReviewChoices[item.field]
                      const isUnresolved = unresolvedFieldSet.has(item.field)
                      return (
                    <Alert
                      key={key}
                      type={isUnresolved ? 'warning' : 'success'}
                      showIcon
                      message={`${item.field}: ${item.reason}`}
                      style={{
                        cursor: 'pointer',
                        borderColor: isActive ? '#1677ff' : undefined,
                        boxShadow: isActive ? '0 0 0 1px rgba(22, 119, 255, 0.18)' : undefined,
                      }}
                      onClick={() => focusReviewItem(item, key)}
                      action={
                        <Space size="small" wrap>
                          <Tag color={isApplied ? 'green' : draft?.draft_mode === 'smart' ? 'blue' : 'gold'}>
                            {isApplied
                              ? '已应用'
                              : draft?.draft_mode === 'smart'
                                ? '智能预选'
                                : '待确认'}
                          </Tag>
                          <Button
                            size="small"
                            onClick={(event) => {
                              event.stopPropagation()
                              focusReviewItem(item, key)
                              toggleReviewItem(key)
                            }}
                            icon={expanded ? <UpOutlined /> : <DownOutlined />}
                          >
                            {expanded ? '收起详情' : '展开详情'}
                          </Button>
                        </Space>
                      }
                      description={
                        expanded ? (
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
                          ) : draft?.draft_mode === 'smart' ? (
                            <Alert
                              type="info"
                              showIcon
                              message="智能 Draft 默认选择"
                              description="该项由 smart mode 自动预选，你仍然可以手动改写。"
                            />
                          ) : null}
                          <Space wrap>
                            <Button
                              size="small"
                              type="primary"
                              onClick={(event) => {
                                event.stopPropagation()
                                void chooseReviewOption(item, item.recommended_option)
                              }}
                              loading={applyReview.isPending}
                            >
                              Apply Recommended
                            </Button>
                            <Button
                              size="small"
                              onClick={(event) => {
                                event.stopPropagation()
                                focusEvidence(item.evidence_refs, `${item.field} · 推荐定位`)
                              }}
                              disabled={!item.evidence_refs.length}
                            >
                              查看推荐定位
                            </Button>
                            <Button
                              size="small"
                              onClick={(event) => {
                                event.stopPropagation()
                                focusEvidence(
                                  collectAllEvidenceRefs(item),
                                  `${item.field} · 全部证据`,
                                )
                              }}
                              disabled={!collectAllEvidenceRefs(item).length}
                            >
                              查看全部证据
                            </Button>
                            {item.alternative_candidates.map((candidate, candidateIndex) => (
                              <Space key={candidateIndex} size="small">
                                <Button
                                  size="small"
                                  onClick={(event) => {
                                    event.stopPropagation()
                                    void chooseReviewOption(item, candidate)
                                  }}
                                  loading={applyReview.isPending}
                                >
                                  Apply Alternative {candidateIndex + 1}
                                </Button>
                                <Button
                                  size="small"
                                  onClick={(event) => {
                                    event.stopPropagation()
                                    focusEvidence(
                                      item.alternative_evidence_refs[candidateIndex] ?? [],
                                      `${item.field} · 备选 ${candidateIndex + 1}`,
                                    )
                                  }}
                                  disabled={!(item.alternative_evidence_refs[candidateIndex] ?? []).length}
                                >
                                  查看备选 {candidateIndex + 1}
                                </Button>
                              </Space>
                            ))}
                          </Space>
                        </Space>
                        ) : null
                      }
                    />
                      )
                    })()
                  ))}
                </Space>
              )}
            </Card>
            <Card title="Connectivity Result" style={{ marginTop: 16 }}>
              {connectivityResult ? (
                <Space direction="vertical" style={{ width: '100%' }}>
                  <Alert
                    type={connectivityResult.status === 'done' ? 'success' : 'warning'}
                    message="Connectivity Test Result"
                    description={
                      connectivityResult.status === 'done'
                        ? '已完成连通性验证，可直接对比规则提取与 LLM 提取结果。'
                        : connectivityResult.error ?? connectivityResult.status
                    }
                  />
                  <ResponseComparison
                    ruleResponse={connectivityResult.responses[0]}
                    llmResponse={connectivityResult.llm_responses?.[0] ?? null}
                    llmError={connectivityResult.llm_errors?.[0] ?? null}
                    llmEnabled={hasLLMExtractionData(
                      connectivityResult.llm_responses,
                      connectivityResult.llm_errors,
                    )}
                  />
                </Space>
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
              }}
            >
              {!runtimeData ? (
                <Empty description="暂无关键截图" />
              ) : (
                <Space direction="vertical" style={{ width: '100%' }} size="middle">
                  {activeReviewEntry ? (
                    <Space direction="vertical" size={4} style={{ width: '100%' }}>
                      <Typography.Text strong>{activeReviewEntry.item.field}</Typography.Text>
                      <Typography.Text type="secondary">{activeReviewEntry.item.reason}</Typography.Text>
                    </Space>
                  ) : null}
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
                  {relatedEvidenceScreens.length ? (
                    <>
                      <Typography.Text strong>Related Evidence</Typography.Text>
                      <List
                        size="small"
                        dataSource={relatedEvidenceScreens}
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
                            }}
                          >
                            <Space direction="vertical" size={0} style={{ width: '100%' }}>
                              <Typography.Text strong={item.path === currentScreen?.path}>
                                {item.label}
                              </Typography.Text>
                              <Typography.Text type="secondary">{item.step}</Typography.Text>
                            </Space>
                          </List.Item>
                        )}
                      />
                    </>
                  ) : null}
                  <List
                    header="All Screens"
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
