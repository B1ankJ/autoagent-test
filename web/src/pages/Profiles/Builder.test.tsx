import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../test/test-utils'
import Builder from './Builder'

const {
  createSessionMock,
  captureStepMock,
  generateDraftMock,
  applyReviewMock,
  validateDraftMock,
  saveProfileMock,
  fetchArtifactBlobUrlMock,
  useVlmMock,
  configureNewSessionMock,
  captureNewSessionStepMock,
  confirmNewSessionStepMock,
} = vi.hoisted(() => ({
  createSessionMock: vi.fn(),
  captureStepMock: vi.fn(),
  generateDraftMock: vi.fn(),
  applyReviewMock: vi.fn(),
  validateDraftMock: vi.fn(),
  saveProfileMock: vi.fn(async () => ({ name: 'qwen_android' })),
  fetchArtifactBlobUrlMock: vi.fn(async (_sessionId: string, name: string) => `blob:${name}`),
  useVlmMock: vi.fn<[], { data: { base_url: string; model: string; api_key: string | null } }>(
    () => ({ data: { base_url: 'u', model: 'm', api_key: 'k' } }),
  ),
  configureNewSessionMock: vi.fn(),
  captureNewSessionStepMock: vi.fn(),
  confirmNewSessionStepMock: vi.fn(),
}))
let runtimeMockData: unknown = null

vi.mock('../../api/profileBuilderRuntime', () => ({
  useProfileBuilderRuntime: () => ({
    data: runtimeMockData,
    isLoading: false,
  }),
  fetchProfileBuilderArtifactBlobUrl: fetchArtifactBlobUrlMock,
}))

vi.mock('../../api/devices', () => ({
  useDevices: () => ({
    isLoading: false,
    data: [
      {
        serial: 'serial-1',
        label: 'Pixel 8',
        model: 'Pixel 8',
        android_version: '15',
        adb_keyboard_installed: true,
        adb_keyboard_enabled: true,
        online: true,
        enabled: true,
        last_seen_at: null,
      },
    ],
  }),
}))

vi.mock('../../api/profileBuilder', () => ({
  useCreateProfileBuilderSession: () => ({
    isPending: false,
    mutateAsync: createSessionMock,
  }),
  useCaptureProfileBuilderStep: () => ({
    isPending: false,
    mutateAsync: captureStepMock,
  }),
  useGenerateProfileBuilderDraft: () => ({
    isPending: false,
    mutateAsync: generateDraftMock,
  }),
  useApplyProfileBuilderReview: () => ({
    isPending: false,
    mutateAsync: applyReviewMock,
  }),
  useValidateProfileBuilderDraft: () => ({
    isPending: false,
    mutateAsync: validateDraftMock,
  }),
  useConfigureProfileBuilderNewSession: () => ({
    isPending: false,
    mutateAsync: configureNewSessionMock,
  }),
  useCaptureProfileBuilderNewSessionStep: () => ({
    isPending: false,
    mutateAsync: captureNewSessionStepMock,
  }),
  useConfirmProfileBuilderNewSessionStep: () => ({
    isPending: false,
    mutateAsync: confirmNewSessionStepMock,
  }),
}))

vi.mock('../../api/profiles', () => ({
  useSaveProfile: () => ({
    isPending: false,
    mutateAsync: saveProfileMock,
  }),
}))

vi.mock('../../api/config', () => ({
  useVLM: () => useVlmMock(),
}))

describe('Builder', () => {
  afterEach(() => {
    vi.clearAllMocks()
    fetchArtifactBlobUrlMock.mockImplementation(async (_sessionId: string, name: string) => `blob:${name}`)
    runtimeMockData = null
    useVlmMock.mockImplementation(() => ({ data: { base_url: 'u', model: 'm', api_key: 'k' } }))
  })

  it('passes rule draft mode and inject toggle independently', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    createSessionMock.mockResolvedValue({
      id: 'pb_1',
      platform: 'android',
      device_serial: 'serial-1',
      name: 'qwen_android',
      status: 'draft',
      steps: ['idle', 'editing'],
      artifact_dir: '/tmp/pb_1',
      artifacts: [],
      captures: [
        {
          step: 'idle',
          package: 'com.aliyun.tongyi',
          activity: '.IdleActivity',
          xml_artifact: 'capture_idle.xml',
          screenshot_artifact: 'capture_idle.png',
          active: true,
          captured_at: '2026-04-23T12:00:00Z',
        },
        {
          step: 'editing',
          package: 'com.aliyun.tongyi',
          activity: '.EditingActivity',
          xml_artifact: 'capture_editing.xml',
          screenshot_artifact: 'capture_editing.png',
          active: true,
          captured_at: '2026-04-23T12:01:00Z',
        },
      ],
    })
    generateDraftMock.mockResolvedValue({
      session: {
        id: 'pb_1',
        platform: 'android',
        device_serial: 'serial-1',
        name: 'qwen_android',
        status: 'ready',
        steps: ['idle', 'editing'],
        artifact_dir: '/tmp/pb_1',
        artifacts: ['draft_profile.yaml'],
        captures: [],
      },
      candidates: { input_candidates: [], send_candidates: [], response_candidates: [], review_items: [] },
      review_items: [],
      draft_profile_yaml: 'name: qwen_android\nplatform: android\n',
      draft_mode: 'rule',
      requires_manual_review: true,
      applied_review_choices: {},
      pending_review_fields: [],
      auto_review_source: 'manual',
    })

    renderWithProviders(<Builder />, { initialPath: '/profiles/builder' })

    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.click(await screen.findByText('Pixel 8'))
    await userEvent.click(screen.getByRole('button', { name: /Start Builder Session/ }))
    await userEvent.click(await screen.findByLabelText('规则 Draft（需人工确认 Review）'))
    await userEvent.click(await screen.findByLabelText('生成时注入 LLM 响应抽取配置'))
    await userEvent.click(screen.getByRole('button', { name: /Generate Draft/ }))

    await waitFor(() => {
      expect(generateDraftMock).toHaveBeenCalledWith({
        sessionId: 'pb_1',
        draftMode: 'rule',
        injectLlm: true,
      })
    })
  })

  it('disables smart draft and llm injection when global VLM config is incomplete', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    useVlmMock.mockImplementation(() => ({ data: { base_url: 'u', model: 'm', api_key: null } }))
    createSessionMock.mockResolvedValue({
      id: 'pb_1',
      platform: 'android',
      device_serial: 'serial-1',
      name: 'qwen_android',
      status: 'draft',
      steps: ['idle', 'editing'],
      artifact_dir: '/tmp/pb_1',
      artifacts: [],
      captures: [
        {
          step: 'idle',
          package: 'com.aliyun.tongyi',
          activity: '.IdleActivity',
          xml_artifact: 'capture_idle.xml',
          screenshot_artifact: 'capture_idle.png',
          active: true,
          captured_at: '2026-04-23T12:00:00Z',
        },
        {
          step: 'editing',
          package: 'com.aliyun.tongyi',
          activity: '.EditingActivity',
          xml_artifact: 'capture_editing.xml',
          screenshot_artifact: 'capture_editing.png',
          active: true,
          captured_at: '2026-04-23T12:01:00Z',
        },
      ],
    })

    renderWithProviders(<Builder />, { initialPath: '/profiles/builder' })

    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.click(await screen.findByText('Pixel 8'))
    await userEvent.click(screen.getByRole('button', { name: /Start Builder Session/ }))

    await waitFor(() => {
      expect(screen.getByLabelText('智能 Draft（LLM 自动选择 Review）')).toBeDisabled()
      expect(screen.getByLabelText('生成时注入 LLM 响应抽取配置')).toBeDisabled()
    })
  })

  it('allows connectivity immediately for smart drafts resolved by backend', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    createSessionMock.mockResolvedValue({
      id: 'pb_1',
      platform: 'android',
      device_serial: 'serial-1',
      name: 'qwen_android',
      status: 'draft',
      steps: ['idle', 'editing'],
      artifact_dir: '/tmp/pb_1',
      artifacts: [],
      captures: [
        {
          step: 'idle',
          package: 'com.aliyun.tongyi',
          activity: '.IdleActivity',
          xml_artifact: 'capture_idle.xml',
          screenshot_artifact: 'capture_idle.png',
          active: true,
          captured_at: '2026-04-23T12:00:00Z',
        },
        {
          step: 'editing',
          package: 'com.aliyun.tongyi',
          activity: '.EditingActivity',
          xml_artifact: 'capture_editing.xml',
          screenshot_artifact: 'capture_editing.png',
          active: true,
          captured_at: '2026-04-23T12:01:00Z',
        },
      ],
    })
    generateDraftMock.mockResolvedValue({
      session: {
        id: 'pb_1',
        platform: 'android',
        device_serial: 'serial-1',
        name: 'qwen_android',
        status: 'ready',
        steps: ['idle', 'editing'],
        artifact_dir: '/tmp/pb_1',
        artifacts: ['draft_profile.yaml'],
        captures: [],
      },
      candidates: { input_candidates: [], send_candidates: [], response_candidates: [], review_items: [] },
      review_items: [
        {
          field: 'send_action',
          reason: 'Confirm how the send control should be triggered in runtime editing state.',
          recommended_option: [{ action: 'tap_xy', x: 964, y: 2064 }],
          alternative_candidates: [],
          evidence_refs: [],
          alternative_evidence_refs: [],
        },
      ],
      draft_profile_yaml: 'name: qwen_android\nplatform: android\n',
      draft_mode: 'smart',
      requires_manual_review: false,
      applied_review_choices: { send_action: 0 },
      pending_review_fields: [],
      auto_review_source: 'llm',
    })

    renderWithProviders(<Builder />, { initialPath: '/profiles/builder' })

    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.click(await screen.findByText('Pixel 8'))
    await userEvent.click(screen.getByRole('button', { name: /Start Builder Session/ }))
    await userEvent.click(await screen.findByLabelText('智能 Draft（LLM 自动选择 Review）'))
    await userEvent.click(screen.getByRole('button', { name: /Generate Draft/ }))

    await waitFor(() => {
      expect(generateDraftMock).toHaveBeenCalledWith({
        sessionId: 'pb_1',
        draftMode: 'smart',
        injectLlm: false,
      })
    })
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Run Connectivity Test/ })).toBeEnabled()
    })
  })

  it('renders guided builder steps', async () => {
    renderWithProviders(<Builder />, { initialPath: '/profiles/builder' })

    expect(await screen.findByText('Build Profile')).toBeInTheDocument()
    expect(screen.getByText('Capture Idle State')).toBeInTheDocument()
    expect(screen.getByText('Capture Editing State')).toBeInTheDocument()
    expect(
      screen.getByText(/请先手动点开输入框并确认当前已经处于编辑态/),
    ).toBeInTheDocument()
    expect(screen.queryByText('Capture Response State')).not.toBeInTheDocument()
  })

  it('creates session, captures steps, and renders draft yaml', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    createSessionMock.mockResolvedValue({
      id: 'pb_1',
      platform: 'android',
      device_serial: 'serial-1',
      name: 'qwen_android',
      status: 'draft',
      steps: ['idle', 'editing'],
      artifact_dir: '/tmp/pb_1',
      artifacts: [],
      captures: [],
    })
    captureStepMock
      .mockResolvedValueOnce({
        id: 'pb_1',
        platform: 'android',
        device_serial: 'serial-1',
        name: 'qwen_android',
        status: 'draft',
        steps: ['idle', 'editing'],
        artifact_dir: '/tmp/pb_1',
        artifacts: ['capture_idle.xml'],
        captures: [
          {
            step: 'idle',
            package: 'com.aliyun.tongyi',
            activity: '.IdleActivity',
            xml_artifact: 'capture_idle.xml',
            screenshot_artifact: 'capture_idle.png',
            active: true,
            captured_at: '2026-04-23T12:00:00Z',
          },
        ],
      })
      .mockResolvedValueOnce({
        id: 'pb_1',
        platform: 'android',
        device_serial: 'serial-1',
        name: 'qwen_android',
        status: 'draft',
        steps: ['idle', 'editing'],
        artifact_dir: '/tmp/pb_1',
        artifacts: ['capture_idle.xml', 'capture_editing.xml'],
        captures: [
          {
            step: 'idle',
            package: 'com.aliyun.tongyi',
            activity: '.IdleActivity',
            xml_artifact: 'capture_idle.xml',
            screenshot_artifact: 'capture_idle.png',
            active: true,
            captured_at: '2026-04-23T12:00:00Z',
          },
          {
            step: 'editing',
            package: 'com.aliyun.tongyi',
            activity: '.EditingActivity',
            xml_artifact: 'capture_editing.xml',
            screenshot_artifact: 'capture_editing.png',
            active: true,
            captured_at: '2026-04-23T12:01:00Z',
          },
        ],
      })
    generateDraftMock.mockResolvedValue({
      session: {
        id: 'pb_1',
        platform: 'android',
        device_serial: 'serial-1',
        name: 'qwen_android',
        status: 'ready',
        steps: ['idle', 'editing'],
        artifact_dir: '/tmp/pb_1',
        artifacts: ['draft_profile.yaml'],
        captures: [],
      },
      candidates: {
        input_candidates: [],
        send_candidates: [],
        response_candidates: [],
        review_items: [],
      },
      review_items: [
        {
          field: 'send_action',
          reason: 'Confirm how the send control should be triggered in runtime editing state.',
          recommended_option: [{ action: 'tap_xy', x: 964, y: 2064 }],
          alternative_candidates: [
            [{ action: 'click_locator', locator: { type: 'xpath', value: '//*[@bounds="[909,2009][1020,2120]"]' } }],
          ],
          evidence_refs: [
            {
              source: 'editing_xml',
              step: 'editing',
              artifact: 'capture_editing.png',
              bounds: [909, 2009, 1020, 2120],
              label: 'send-button',
            },
          ],
          alternative_evidence_refs: [
            [
              {
                source: 'editing_xml',
                step: 'editing',
                artifact: 'capture_editing.png',
                bounds: [909, 2009, 1020, 2120],
                label: 'send-button',
              },
            ],
          ],
        },
      ],
      draft_profile_yaml: 'name: qwen_android\nplatform: android\n',
      draft_mode: 'rule',
      requires_manual_review: true,
      applied_review_choices: {},
      pending_review_fields: ['send_action'],
      auto_review_source: 'manual',
    })
    applyReviewMock.mockResolvedValue({
      session: {
        id: 'pb_1',
        platform: 'android',
        device_serial: 'serial-1',
        name: 'qwen_android',
        status: 'ready',
        steps: ['idle', 'editing'],
        artifact_dir: '/tmp/pb_1',
        artifacts: ['draft_profile.yaml'],
        captures: [],
      },
      draft_profile_yaml: 'name: qwen_android\nplatform: android\nsend_action:\n',
    })
    validateDraftMock.mockResolvedValue({
      session: {
        id: 'pb_1',
        platform: 'android',
        device_serial: 'serial-1',
        name: 'qwen_android',
        status: 'validated',
        steps: ['idle', 'editing'],
        artifact_dir: '/tmp/pb_1',
        artifacts: ['draft_profile.yaml', 'connectivity_result.json'],
        captures: [],
      },
      draft_profile_yaml: 'name: qwen_android\nplatform: android\nsend_action:\n',
      connectivity_result: {
        id: 'conn-1',
        status: 'done',
        responses: ['pong'],
        llm_responses: ['llm pong'],
        llm_errors: [null],
      },
    })

    renderWithProviders(<Builder />, { initialPath: '/profiles/builder' })

    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.click(await screen.findByText('Pixel 8'))
    await userEvent.click(screen.getByRole('button', { name: /Start Builder Session/ }))

    const captureButtons = await screen.findAllByRole('button', { name: 'Capture' })
    await userEvent.click(captureButtons[0])
    await userEvent.click(captureButtons[1])
    await userEvent.click(screen.getByRole('button', { name: /Generate Draft/ }))
    await userEvent.click(screen.getByRole('button', { name: /展开详情/ }))
    await userEvent.click(screen.getByRole('button', { name: '查看推荐定位' }))
    await userEvent.click(screen.getByRole('button', { name: 'Apply Recommended' }))
    expect(screen.getByText('当前已应用')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Apply Recommended' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '保存/覆盖到 Profiles' }))
    await userEvent.click(screen.getByRole('button', { name: /Run Connectivity Test/ }))

    await waitFor(() => {
      expect(generateDraftMock).toHaveBeenCalledWith({
        sessionId: 'pb_1',
        draftMode: 'smart',
        injectLlm: false,
      })
    })
    expect(applyReviewMock).toHaveBeenCalled()
    expect(saveProfileMock).toHaveBeenCalledWith({
      name: 'qwen_android',
      yaml: 'name: qwen_android\nplatform: android\nsend_action:\n',
      create: true,
    })
    expect(fetchArtifactBlobUrlMock).toHaveBeenCalledWith('pb_1', 'capture_editing.png')
    expect(validateDraftMock).toHaveBeenCalledWith('pb_1')
    expect(screen.getByDisplayValue(/name: qwen_android/)).toBeInTheDocument()
    expect(screen.getByText('Connectivity Test Result')).toBeInTheDocument()
    expect(screen.getByText('pong')).toBeInTheDocument()
    expect(screen.getByText('llm pong')).toBeInTheDocument()
  })

  it('loads manual editing evidence screenshots from review items', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    createSessionMock.mockResolvedValue({
      id: 'pb_1',
      platform: 'android',
      device_serial: 'serial-1',
      name: 'qwen_android',
      status: 'ready',
      steps: ['idle', 'editing'],
      artifact_dir: '/tmp/pb_1',
      artifacts: ['draft_profile.yaml', 'capture_editing.png'],
      captures: [
        {
          step: 'idle',
          package: 'com.aliyun.tongyi',
          activity: '.IdleActivity',
          xml_artifact: 'capture_idle.xml',
          screenshot_artifact: 'capture_idle.png',
          active: true,
          captured_at: '2026-04-23T12:00:00Z',
        },
        {
          step: 'editing',
          package: 'com.aliyun.tongyi',
          activity: '.EditingActivity',
          xml_artifact: 'capture_editing.xml',
          screenshot_artifact: 'capture_editing.png',
          active: true,
          captured_at: '2026-04-23T12:01:00Z',
        },
      ],
    })
    generateDraftMock.mockResolvedValue({
      session: {
        id: 'pb_1',
        platform: 'android',
        device_serial: 'serial-1',
        name: 'qwen_android',
        status: 'ready',
        steps: ['idle', 'editing'],
        artifact_dir: '/tmp/pb_1',
        artifacts: ['draft_profile.yaml', 'capture_editing.png'],
        captures: [
          {
            step: 'idle',
            package: 'com.aliyun.tongyi',
            activity: '.IdleActivity',
            xml_artifact: 'capture_idle.xml',
            screenshot_artifact: 'capture_idle.png',
            active: true,
            captured_at: '2026-04-23T12:00:00Z',
          },
          {
            step: 'editing',
            package: 'com.aliyun.tongyi',
            activity: '.EditingActivity',
            xml_artifact: 'capture_editing.xml',
            screenshot_artifact: 'capture_editing.png',
            active: true,
            captured_at: '2026-04-23T12:01:00Z',
          },
        ],
      },
      candidates: {
        input_candidates: [],
        send_candidates: [],
        response_candidates: [],
        review_items: [],
      },
      review_items: [
        {
          field: 'send_action',
          reason: 'Multiple clickable controls looked like send buttons.',
          recommended_option: [{ action: 'tap_xy', x: 964, y: 2064 }],
          alternative_candidates: [
            [{ action: 'click_locator', locator: { type: 'xpath', value: '//*[@bounds="[909,2009][1020,2120]"]' } }],
            [{ action: 'tap_xy', x: 964, y: 1346 }],
          ],
          evidence_refs: [
            {
              source: 'editing_xml',
              step: 'editing',
              artifact: 'capture_editing.png',
              bounds: [909, 2009, 1020, 2120],
              label: 'send-button',
            },
          ],
          alternative_evidence_refs: [
            [
              {
                source: 'editing_xml',
                step: 'editing',
                artifact: 'capture_editing.png',
                bounds: [909, 2009, 1020, 2120],
                label: 'send-button',
              },
            ],
            [
              {
                source: 'editing_xml',
                step: 'editing',
                artifact: 'capture_editing.png',
                bounds: [909, 1291, 1020, 1402],
                label: 'send-button',
              },
            ],
          ],
        },
      ],
      draft_profile_yaml: 'name: qwen_android\nplatform: android\n',
      draft_mode: 'rule',
      requires_manual_review: true,
      applied_review_choices: {},
      pending_review_fields: ['send_action'],
      auto_review_source: 'manual',
    })

    renderWithProviders(<Builder />, { initialPath: '/profiles/builder' })

    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.click(await screen.findByText('Pixel 8'))
    await userEvent.click(screen.getByRole('button', { name: /Start Builder Session/ }))
    await userEvent.click(screen.getByRole('button', { name: /Generate Draft/ }))
    await userEvent.click(screen.getByRole('button', { name: /展开详情/ }))
    await userEvent.click(screen.getByRole('button', { name: '查看全部证据' }))

    await waitFor(() => {
      expect(fetchArtifactBlobUrlMock).toHaveBeenCalledWith('pb_1', 'capture_editing.png')
    })
  })

  it('keeps alternative evidence focus when clicking 查看备选', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    createSessionMock.mockResolvedValue({
      id: 'pb_1',
      platform: 'android',
      device_serial: 'serial-1',
      name: 'qwen_android',
      status: 'ready',
      steps: ['idle', 'editing'],
      artifact_dir: '/tmp/pb_1',
      artifacts: ['draft_profile.yaml', 'capture_editing.png'],
      captures: [
        {
          step: 'idle',
          package: 'com.aliyun.tongyi',
          activity: '.IdleActivity',
          xml_artifact: 'capture_idle.xml',
          screenshot_artifact: 'capture_idle.png',
          active: true,
          captured_at: '2026-04-23T12:00:00Z',
        },
        {
          step: 'editing',
          package: 'com.aliyun.tongyi',
          activity: '.EditingActivity',
          xml_artifact: 'capture_editing.xml',
          screenshot_artifact: 'capture_editing.png',
          active: true,
          captured_at: '2026-04-23T12:01:00Z',
        },
      ],
    })
    runtimeMockData = {
      session_id: 'pb_1',
      session_status: 'ready',
      current_step: 'generate_draft',
      step_state: 'done',
      last_error: null,
      captures: [
        { step: 'idle', status: 'done', screenshot: 'capture_idle.png', updated_at: '2026-04-23T12:00:00Z' },
        { step: 'editing', status: 'done', screenshot: 'capture_editing.png', updated_at: '2026-04-23T12:01:00Z' },
      ],
      connectivity: {
        status: 'idle',
        result_status: null,
        result_summary: null,
        screens: [],
      },
      recent_screens: [
        { step: 'idle', label: 'capture_idle', path: 'capture_idle.png', taken_at: '2026-04-23T12:00:00Z' },
        { step: 'editing', label: 'capture_editing', path: 'capture_editing.png', taken_at: '2026-04-23T12:01:00Z' },
      ],
    }
    generateDraftMock.mockResolvedValue({
      session: {
        id: 'pb_1',
        platform: 'android',
        device_serial: 'serial-1',
        name: 'qwen_android',
        status: 'ready',
        steps: ['idle', 'editing'],
        artifact_dir: '/tmp/pb_1',
        artifacts: ['draft_profile.yaml', 'capture_editing.png'],
        captures: [
          {
            step: 'idle',
            package: 'com.aliyun.tongyi',
            activity: '.IdleActivity',
            xml_artifact: 'capture_idle.xml',
            screenshot_artifact: 'capture_idle.png',
            active: true,
            captured_at: '2026-04-23T12:00:00Z',
          },
          {
            step: 'editing',
            package: 'com.aliyun.tongyi',
            activity: '.EditingActivity',
            xml_artifact: 'capture_editing.xml',
            screenshot_artifact: 'capture_editing.png',
            active: true,
            captured_at: '2026-04-23T12:01:00Z',
          },
        ],
      },
      candidates: {
        input_candidates: [],
        send_candidates: [],
        response_candidates: [],
        review_items: [],
      },
      review_items: [
        {
          field: 'send_action',
          reason: 'Multiple clickable controls looked like send buttons.',
          recommended_option: [{ action: 'tap_xy', x: 964, y: 2064 }],
          alternative_candidates: [
            [{ action: 'click_locator', locator: { type: 'xpath', value: '//*[@bounds="[909,2009][1020,2120]"]' } }],
            [{ action: 'tap_xy', x: 964, y: 1346 }],
          ],
          evidence_refs: [
            {
              source: 'editing_xml',
              step: 'editing',
              artifact: 'capture_editing.png',
              bounds: [909, 2009, 1020, 2120],
              label: 'send-button',
            },
          ],
          alternative_evidence_refs: [
            [
              {
                source: 'editing_xml',
                step: 'editing',
                artifact: 'capture_editing.png',
                bounds: [909, 2009, 1020, 2120],
                label: 'send-button',
              },
            ],
            [
              {
                source: 'editing_xml',
                step: 'editing',
                artifact: 'capture_editing.png',
                bounds: [909, 1291, 1020, 1402],
                label: 'send-button',
              },
            ],
          ],
        },
      ],
      draft_profile_yaml: 'name: qwen_android\nplatform: android\n',
      draft_mode: 'rule',
      requires_manual_review: true,
      applied_review_choices: {},
      pending_review_fields: ['send_action'],
      auto_review_source: 'manual',
    })

    renderWithProviders(<Builder />, { initialPath: '/profiles/builder' })

    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.click(await screen.findByText('Pixel 8'))
    await userEvent.click(screen.getByRole('button', { name: /Start Builder Session/ }))
    await userEvent.click(screen.getAllByRole('button', { name: /Generate Draft/ })[0])
    await userEvent.click(screen.getByRole('button', { name: /展开详情/ }))
    await userEvent.click(screen.getByRole('button', { name: '查看备选 2' }))

    expect(await screen.findByText('send_action · 备选 2')).toBeInTheDocument()
    expect(screen.queryByText('send_action · 推荐定位')).not.toBeInTheDocument()
  })

  it('applies recommended input_focus_action review options', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    createSessionMock.mockResolvedValue({
      id: 'pb_1',
      platform: 'android',
      device_serial: 'serial-1',
      name: 'qwen_android',
      status: 'ready',
      steps: ['idle', 'editing'],
      artifact_dir: '/tmp/pb_1',
      artifacts: ['draft_profile.yaml', 'capture_idle.png'],
      captures: [
        {
          step: 'idle',
          package: 'com.aliyun.tongyi',
          activity: '.IdleActivity',
          xml_artifact: 'capture_idle.xml',
          screenshot_artifact: 'capture_idle.png',
          active: true,
          captured_at: '2026-04-23T12:00:00Z',
        },
        {
          step: 'editing',
          package: 'com.aliyun.tongyi',
          activity: '.EditingActivity',
          xml_artifact: 'capture_editing.xml',
          screenshot_artifact: 'capture_editing.png',
          active: true,
          captured_at: '2026-04-23T12:01:00Z',
        },
      ],
    })
    generateDraftMock.mockResolvedValue({
      session: {
        id: 'pb_1',
        platform: 'android',
        device_serial: 'serial-1',
        name: 'qwen_android',
        status: 'ready',
        steps: ['idle', 'editing'],
        artifact_dir: '/tmp/pb_1',
        artifacts: ['draft_profile.yaml', 'capture_idle.png'],
        captures: [
          {
            step: 'idle',
            package: 'com.aliyun.tongyi',
            activity: '.IdleActivity',
            xml_artifact: 'capture_idle.xml',
            screenshot_artifact: 'capture_idle.png',
            active: true,
            captured_at: '2026-04-23T12:00:00Z',
          },
          {
            step: 'editing',
            package: 'com.aliyun.tongyi',
            activity: '.EditingActivity',
            xml_artifact: 'capture_editing.xml',
            screenshot_artifact: 'capture_editing.png',
            active: true,
            captured_at: '2026-04-23T12:01:00Z',
          },
        ],
      },
      candidates: {
        input_candidates: [],
        send_candidates: [],
        response_candidates: [],
        review_items: [],
      },
        review_items: [
        {
          field: 'input_focus_action',
          reason: 'Multiple entry actions are available for focusing the input area.',
          recommended_option: [{ action: 'tap_xy', x: 477, y: 2094 }],
          alternative_candidates: [
            [{ action: 'click_locator', locator: { type: 'xpath', value: '//*[contains(@text, "发消息")]' } }],
          ],
          evidence_refs: [
            {
              source: 'idle_xml',
              step: 'idle',
              artifact: 'capture_idle.png',
              bounds: [177, 2066, 777, 2123],
              label: 'entry-action',
            },
          ],
          alternative_evidence_refs: [
            [
              {
                source: 'idle_xml',
                step: 'idle',
                artifact: 'capture_idle.png',
                bounds: [177, 2066, 777, 2123],
                label: 'entry-action',
              },
            ],
          ],
        },
      ],
      draft_profile_yaml: 'name: qwen_android\nplatform: android\n',
      draft_mode: 'rule',
      requires_manual_review: true,
      applied_review_choices: {},
      pending_review_fields: ['input_focus_action'],
      auto_review_source: 'manual',
    })
    applyReviewMock.mockResolvedValue({
      session: {
        id: 'pb_1',
        platform: 'android',
        device_serial: 'serial-1',
        name: 'qwen_android',
        status: 'ready',
        steps: ['idle', 'editing'],
        artifact_dir: '/tmp/pb_1',
        artifacts: ['draft_profile.yaml', 'capture_idle.png'],
        captures: [],
      },
      draft_profile_yaml: 'name: qwen_android\nplatform: android\ninput_focus_action:\n',
    })

    renderWithProviders(<Builder />, { initialPath: '/profiles/builder' })

    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.click(await screen.findByText('Pixel 8'))
    await userEvent.click(screen.getByRole('button', { name: /Start Builder Session/ }))
    await userEvent.click(screen.getByRole('button', { name: /Generate Draft/ }))
    await userEvent.click(screen.getByRole('button', { name: /展开详情/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Apply Recommended' }))

    await waitFor(() => {
      expect(applyReviewMock).toHaveBeenCalledWith({
        sessionId: 'pb_1',
        payload: {
          input_focus_action: [{ action: 'tap_xy', x: 477, y: 2094 }],
        },
      })
    })
  })

  it('disables connectivity validation until all review items are confirmed', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    createSessionMock.mockResolvedValue({
      id: 'pb_1',
      platform: 'android',
      device_serial: 'serial-1',
      name: 'qwen_android',
      status: 'draft',
      steps: ['idle', 'editing'],
      artifact_dir: '/tmp/pb_1',
      artifacts: ['draft_profile.yaml'],
      captures: [],
    })
    captureStepMock
      .mockResolvedValueOnce({
        id: 'pb_1',
        platform: 'android',
        device_serial: 'serial-1',
        name: 'qwen_android',
        status: 'draft',
        steps: ['idle', 'editing'],
        artifact_dir: '/tmp/pb_1',
        artifacts: ['capture_idle.xml'],
        captures: [
          {
            step: 'idle',
            package: 'com.aliyun.tongyi',
            activity: '.IdleActivity',
            xml_artifact: 'capture_idle.xml',
            screenshot_artifact: 'capture_idle.png',
            active: true,
            captured_at: '2026-04-23T12:00:00Z',
          },
        ],
      })
      .mockResolvedValueOnce({
        id: 'pb_1',
        platform: 'android',
        device_serial: 'serial-1',
        name: 'qwen_android',
        status: 'draft',
        steps: ['idle', 'editing'],
        artifact_dir: '/tmp/pb_1',
        artifacts: ['capture_idle.xml', 'capture_editing.xml'],
        captures: [
          {
            step: 'idle',
            package: 'com.aliyun.tongyi',
            activity: '.IdleActivity',
            xml_artifact: 'capture_idle.xml',
            screenshot_artifact: 'capture_idle.png',
            active: true,
            captured_at: '2026-04-23T12:00:00Z',
          },
          {
            step: 'editing',
            package: 'com.aliyun.tongyi',
            activity: '.EditingActivity',
            xml_artifact: 'capture_editing.xml',
            screenshot_artifact: 'capture_editing.png',
            active: true,
            captured_at: '2026-04-23T12:01:00Z',
          },
        ],
      })
    generateDraftMock.mockResolvedValue({
      session: {
        id: 'pb_1',
        platform: 'android',
        device_serial: 'serial-1',
        name: 'qwen_android',
        status: 'ready',
        steps: ['idle', 'editing'],
        artifact_dir: '/tmp/pb_1',
        artifacts: ['draft_profile.yaml'],
        captures: [],
      },
      candidates: {
        input_candidates: [],
        send_candidates: [],
        response_candidates: [],
        review_items: [],
      },
      review_items: [
        {
          field: 'input_locator',
          reason: 'Multiple input candidates matched the editing capture.',
          recommended_option: { type: 'xpath', value: '//*[@class="android.widget.EditText"]' },
          alternative_candidates: [{ type: 'xpath', value: '//*[contains(@text, "发消息")]' }],
          evidence_refs: [],
          alternative_evidence_refs: [[]],
        },
      ],
      draft_profile_yaml: 'name: qwen_android\nplatform: android\n',
      draft_mode: 'rule',
      requires_manual_review: true,
      applied_review_choices: {},
      pending_review_fields: ['input_locator'],
      auto_review_source: 'manual',
    })
    applyReviewMock.mockResolvedValue({
      session: {
        id: 'pb_1',
        platform: 'android',
        device_serial: 'serial-1',
        name: 'qwen_android',
        status: 'ready',
        steps: ['idle', 'editing'],
        artifact_dir: '/tmp/pb_1',
        artifacts: ['draft_profile.yaml'],
        captures: [],
      },
      draft_profile_yaml: 'name: qwen_android\nplatform: android\ninput_locator:\n',
    })

    renderWithProviders(<Builder />, { initialPath: '/profiles/builder' })

    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.click(await screen.findByText('Pixel 8'))
    await userEvent.click(screen.getByRole('button', { name: /Start Builder Session/ }))
    const captureButtons = await screen.findAllByRole('button', { name: 'Capture' })
    await userEvent.click(captureButtons[0])
    await userEvent.click(captureButtons[1])
    await userEvent.click(screen.getByRole('button', { name: /Generate Draft/ }))

    expect(screen.getByRole('button', { name: /Run Connectivity Test/ })).toBeDisabled()

    await userEvent.click(screen.getByRole('button', { name: /展开详情/ }))
    await userEvent.click(await screen.findByRole('button', { name: 'Apply Recommended' }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Run Connectivity Test/ })).toBeEnabled()
    })
  })

  it('collapses review items by default and toggles details on demand', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    createSessionMock.mockResolvedValue({
      id: 'pb_1',
      platform: 'android',
      device_serial: 'serial-1',
      name: 'qwen_android',
      status: 'ready',
      steps: ['idle', 'editing'],
      artifact_dir: '/tmp/pb_1',
      artifacts: ['draft_profile.yaml'],
      captures: [
        {
          step: 'idle',
          package: 'com.aliyun.tongyi',
          activity: '.IdleActivity',
          xml_artifact: 'capture_idle.xml',
          screenshot_artifact: 'capture_idle.png',
          active: true,
          captured_at: '2026-04-23T12:00:00Z',
        },
        {
          step: 'editing',
          package: 'com.aliyun.tongyi',
          activity: '.EditingActivity',
          xml_artifact: 'capture_editing.xml',
          screenshot_artifact: 'capture_editing.png',
          active: true,
          captured_at: '2026-04-23T12:01:00Z',
        },
      ],
    })
    generateDraftMock.mockResolvedValue({
      session: {
        id: 'pb_1',
        platform: 'android',
        device_serial: 'serial-1',
        name: 'qwen_android',
        status: 'ready',
        steps: ['idle', 'editing'],
        artifact_dir: '/tmp/pb_1',
        artifacts: ['draft_profile.yaml'],
        captures: [],
      },
      candidates: {
        input_candidates: [],
        send_candidates: [],
        response_candidates: [],
        review_items: [],
      },
      review_items: [
        {
          field: 'send_action',
          reason: 'Confirm how the send control should be triggered in runtime editing state.',
          recommended_option: [{ action: 'tap_xy', x: 964, y: 2064 }],
          alternative_candidates: [],
          evidence_refs: [],
          alternative_evidence_refs: [],
        },
      ],
      draft_profile_yaml: 'name: qwen_android\nplatform: android\n',
      draft_mode: 'rule',
      requires_manual_review: true,
      applied_review_choices: {},
      pending_review_fields: ['send_action'],
      auto_review_source: 'manual',
    })

    renderWithProviders(<Builder />, { initialPath: '/profiles/builder' })

    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.click(await screen.findByText('Pixel 8'))
    await userEvent.click(screen.getByRole('button', { name: /Start Builder Session/ }))
    await userEvent.click(screen.getByRole('button', { name: /Generate Draft/ }))

    expect(screen.queryByRole('button', { name: 'Apply Recommended' })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /展开详情/ }))
    expect(await screen.findByRole('button', { name: 'Apply Recommended' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /收起详情/ }))
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: 'Apply Recommended' })).not.toBeInTheDocument()
    })
  })

  it('filters review items to unresolved entries only', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    createSessionMock.mockResolvedValue({
      id: 'pb_1',
      platform: 'android',
      device_serial: 'serial-1',
      name: 'qwen_android',
      status: 'ready',
      steps: ['idle', 'editing'],
      artifact_dir: '/tmp/pb_1',
      artifacts: ['draft_profile.yaml'],
      captures: [
        {
          step: 'idle',
          package: 'com.aliyun.tongyi',
          activity: '.IdleActivity',
          xml_artifact: 'capture_idle.xml',
          screenshot_artifact: 'capture_idle.png',
          active: true,
          captured_at: '2026-04-23T12:00:00Z',
        },
        {
          step: 'editing',
          package: 'com.aliyun.tongyi',
          activity: '.EditingActivity',
          xml_artifact: 'capture_editing.xml',
          screenshot_artifact: 'capture_editing.png',
          active: true,
          captured_at: '2026-04-23T12:01:00Z',
        },
      ],
    })
    generateDraftMock.mockResolvedValue({
      session: {
        id: 'pb_1',
        platform: 'android',
        device_serial: 'serial-1',
        name: 'qwen_android',
        status: 'ready',
        steps: ['idle', 'editing'],
        artifact_dir: '/tmp/pb_1',
        artifacts: ['draft_profile.yaml'],
        captures: [],
      },
      candidates: {
        input_candidates: [],
        send_candidates: [],
        response_candidates: [],
        review_items: [],
      },
      review_items: [
        {
          field: 'send_action',
          reason: 'Confirm send action.',
          recommended_option: [{ action: 'tap_xy', x: 964, y: 2064 }],
          alternative_candidates: [],
          evidence_refs: [],
          alternative_evidence_refs: [],
        },
        {
          field: 'input_locator',
          reason: 'Confirm input locator.',
          recommended_option: { type: 'xpath', value: '//*[@class="android.widget.EditText"]' },
          alternative_candidates: [],
          evidence_refs: [],
          alternative_evidence_refs: [],
        },
      ],
      draft_profile_yaml: 'name: qwen_android\nplatform: android\n',
      draft_mode: 'rule',
      requires_manual_review: true,
      applied_review_choices: { send_action: 0 },
      pending_review_fields: ['input_locator'],
      auto_review_source: 'manual',
    })

    renderWithProviders(<Builder />, { initialPath: '/profiles/builder' })

    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.click(await screen.findByText('Pixel 8'))
    await userEvent.click(screen.getByRole('button', { name: /Start Builder Session/ }))
    await userEvent.click(screen.getByRole('button', { name: /Generate Draft/ }))

    expect(screen.getByText(/send_action: Confirm send action/)).toBeInTheDocument()
    expect(screen.getByText(/input_locator: Confirm input locator/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('checkbox', { name: /仅看未完成/ }))

    expect(screen.queryByText(/send_action: Confirm send action/)).not.toBeInTheDocument()
    expect(screen.getByText(/input_locator: Confirm input locator/)).toBeInTheDocument()
  })

  it('switches key screen preview when selecting a different review item', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    createSessionMock.mockResolvedValue({
      id: 'pb_1',
      platform: 'android',
      device_serial: 'serial-1',
      name: 'qwen_android',
      status: 'ready',
      steps: ['idle', 'editing'],
      artifact_dir: '/tmp/pb_1',
      artifacts: ['draft_profile.yaml', 'capture_idle.png', 'capture_editing.png'],
      captures: [
        {
          step: 'idle',
          package: 'com.aliyun.tongyi',
          activity: '.IdleActivity',
          xml_artifact: 'capture_idle.xml',
          screenshot_artifact: 'capture_idle.png',
          active: true,
          captured_at: '2026-04-23T12:00:00Z',
        },
        {
          step: 'editing',
          package: 'com.aliyun.tongyi',
          activity: '.EditingActivity',
          xml_artifact: 'capture_editing.xml',
          screenshot_artifact: 'capture_editing.png',
          active: true,
          captured_at: '2026-04-23T12:01:00Z',
        },
      ],
    })
    generateDraftMock.mockResolvedValue({
      session: {
        id: 'pb_1',
        platform: 'android',
        device_serial: 'serial-1',
        name: 'qwen_android',
        status: 'ready',
        steps: ['idle', 'editing'],
        artifact_dir: '/tmp/pb_1',
        artifacts: ['draft_profile.yaml', 'capture_idle.png', 'capture_editing.png'],
        captures: [],
      },
      candidates: {
        input_candidates: [],
        send_candidates: [],
        response_candidates: [],
        review_items: [],
      },
      review_items: [
        {
          field: 'input_focus_action',
          reason: 'Confirm entry action.',
          recommended_option: [{ action: 'tap_xy', x: 477, y: 2094 }],
          alternative_candidates: [],
          evidence_refs: [
            {
              source: 'idle_xml',
              step: 'idle',
              artifact: 'capture_idle.png',
              bounds: [177, 2066, 777, 2123],
              label: 'entry-action',
            },
          ],
          alternative_evidence_refs: [],
        },
        {
          field: 'send_action',
          reason: 'Confirm send action.',
          recommended_option: [{ action: 'tap_xy', x: 964, y: 2064 }],
          alternative_candidates: [],
          evidence_refs: [
            {
              source: 'editing_xml',
              step: 'editing',
              artifact: 'capture_editing.png',
              bounds: [909, 2009, 1020, 2120],
              label: 'send-button',
            },
          ],
          alternative_evidence_refs: [],
        },
      ],
      draft_profile_yaml: 'name: qwen_android\nplatform: android\n',
      draft_mode: 'rule',
      requires_manual_review: true,
      applied_review_choices: {},
      pending_review_fields: ['input_focus_action', 'send_action'],
      auto_review_source: 'manual',
    })

    renderWithProviders(<Builder />, { initialPath: '/profiles/builder' })

    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.click(await screen.findByText('Pixel 8'))
    await userEvent.click(screen.getByRole('button', { name: /Start Builder Session/ }))
    await userEvent.click(screen.getByRole('button', { name: /Generate Draft/ }))

    await waitFor(() => {
      expect(fetchArtifactBlobUrlMock).toHaveBeenCalledWith('pb_1', 'capture_idle.png')
    })

    await userEvent.click(screen.getByText(/send_action: Confirm send action/))

    await waitFor(() => {
      expect(fetchArtifactBlobUrlMock).toHaveBeenCalledWith('pb_1', 'capture_editing.png')
    })
  })

  it('renders key screens without nested internal scrolling', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    createSessionMock.mockResolvedValue({
      id: 'pb_1',
      platform: 'android',
      device_serial: 'serial-1',
      name: 'qwen_android',
      status: 'ready',
      steps: ['idle', 'editing'],
      artifact_dir: '/tmp/pb_1',
      artifacts: ['draft_profile.yaml', 'capture_idle.png'],
      captures: [
        {
          step: 'idle',
          package: 'com.aliyun.tongyi',
          activity: '.IdleActivity',
          xml_artifact: 'capture_idle.xml',
          screenshot_artifact: 'capture_idle.png',
          active: true,
          captured_at: '2026-04-23T12:00:00Z',
        },
        {
          step: 'editing',
          package: 'com.aliyun.tongyi',
          activity: '.EditingActivity',
          xml_artifact: 'capture_editing.xml',
          screenshot_artifact: 'capture_editing.png',
          active: true,
          captured_at: '2026-04-23T12:01:00Z',
        },
      ],
    })
    generateDraftMock.mockResolvedValue({
      session: {
        id: 'pb_1',
        platform: 'android',
        device_serial: 'serial-1',
        name: 'qwen_android',
        status: 'ready',
        steps: ['idle', 'editing'],
        artifact_dir: '/tmp/pb_1',
        artifacts: ['draft_profile.yaml', 'capture_idle.png'],
        captures: [],
      },
      candidates: {
        input_candidates: [],
        send_candidates: [],
        response_candidates: [],
        review_items: [],
      },
      review_items: [],
      draft_profile_yaml: 'name: qwen_android\nplatform: android\n',
      draft_mode: 'rule',
      requires_manual_review: false,
      applied_review_choices: {},
      pending_review_fields: [],
      auto_review_source: 'manual',
    })

    renderWithProviders(<Builder />, { initialPath: '/profiles/builder' })

    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.click(await screen.findByText('Pixel 8'))
    await userEvent.click(screen.getByRole('button', { name: /Start Builder Session/ }))
    await userEvent.click(screen.getByRole('button', { name: /Generate Draft/ }))

    const keyScreensCard = screen.getByText('Key Screens').closest('.ant-card')
    expect(keyScreensCard).not.toHaveStyle({ overflowY: 'auto' })
    expect(keyScreensCard).not.toHaveStyle({ maxHeight: 'calc(100vh - 32px)' })
  })

  it('requires explicit confirmation before starting builder session', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)

    renderWithProviders(<Builder />, { initialPath: '/profiles/builder' })

    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.click(await screen.findByText('Pixel 8'))
    await userEvent.click(screen.getByRole('button', { name: /Start Builder Session/ }))

    expect(confirmSpy).toHaveBeenCalled()
    expect(createSessionMock).not.toHaveBeenCalled()
  })

  it('renders input locator review evidence separately from action reviews', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    createSessionMock.mockResolvedValue({
      id: 'pb_1',
      platform: 'android',
      device_serial: 'serial-1',
      name: 'qwen_android',
      status: 'ready',
      steps: ['idle', 'editing'],
      artifact_dir: '/tmp/pb_1',
      artifacts: ['draft_profile.yaml', 'capture_idle.png', 'capture_editing.png'],
      captures: [
        {
          step: 'idle',
          package: 'com.aliyun.tongyi',
          activity: '.IdleActivity',
          xml_artifact: 'capture_idle.xml',
          screenshot_artifact: 'capture_idle.png',
          active: true,
          captured_at: '2026-04-23T12:00:00Z',
        },
        {
          step: 'editing',
          package: 'com.aliyun.tongyi',
          activity: '.EditingActivity',
          xml_artifact: 'capture_editing.xml',
          screenshot_artifact: 'capture_editing.png',
          active: true,
          captured_at: '2026-04-23T12:01:00Z',
        },
      ],
    })
    generateDraftMock.mockResolvedValue({
      session: {
        id: 'pb_1',
        platform: 'android',
        device_serial: 'serial-1',
        name: 'qwen_android',
        status: 'ready',
        steps: ['idle', 'editing'],
        artifact_dir: '/tmp/pb_1',
        artifacts: ['draft_profile.yaml', 'capture_idle.png', 'capture_editing.png'],
        captures: [],
      },
      candidates: {
        input_candidates: [],
        send_candidates: [],
        response_candidates: [],
        review_items: [],
      },
      review_items: [
        {
          field: 'input_locator',
          reason: 'Multiple input candidates matched the editing capture.',
          recommended_option: { type: 'xpath', value: '//*[@class="android.widget.EditText"]' },
          alternative_candidates: [{ type: 'xpath', value: '//*[contains(@text, "发消息")]' }],
          evidence_refs: [
            {
              source: 'editing_xml',
              step: 'editing',
              artifact: 'capture_editing.png',
              locator: { type: 'xpath', value: '//*[@class="android.widget.EditText"]' },
              bounds: [36, 1882, 1032, 2002],
              label: 'input',
            },
          ],
          alternative_evidence_refs: [
            [
              {
                source: 'idle_xml',
                step: 'idle',
                artifact: 'capture_idle.png',
                locator: { type: 'xpath', value: '//*[contains(@text, "发消息")]' },
                bounds: [177, 2066, 777, 2123],
                label: 'input-placeholder',
              },
            ],
          ],
        },
      ],
      draft_profile_yaml: 'name: qwen_android\nplatform: android\n',
      draft_mode: 'rule',
      requires_manual_review: true,
      applied_review_choices: {},
      pending_review_fields: ['input_locator'],
      auto_review_source: 'manual',
    })

    renderWithProviders(<Builder />, { initialPath: '/profiles/builder' })

    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.click(await screen.findByText('Pixel 8'))
    await userEvent.click(screen.getByRole('button', { name: /Start Builder Session/ }))
    await userEvent.click(screen.getByRole('button', { name: /Generate Draft/ }))

    expect(screen.getByText(/input_locator: Multiple input candidates matched the editing capture\./)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /展开详情/ }))
    await userEvent.click(screen.getByRole('button', { name: '查看推荐定位' }))

    await waitFor(() => {
      expect(fetchArtifactBlobUrlMock).toHaveBeenCalledWith('pb_1', 'capture_editing.png')
    })
  })

  it('renders runtime status and key screens when runtime data is available', async () => {
    createSessionMock.mockResolvedValue({
      id: 'pb_1',
      platform: 'android',
      device_serial: 'serial-1',
      name: 'qwen_android',
      status: 'draft',
      steps: ['idle', 'editing'],
      artifact_dir: '/tmp/pb_1',
      artifacts: [],
      captures: [],
    })
    runtimeMockData = {
      session_id: 'pb_1',
      session_status: 'validating',
      current_step: 'connectivity',
      step_state: 'running',
      last_error: null,
      captures: [
        { step: 'idle', status: 'done', screenshot: 'capture_idle.png', updated_at: null },
        { step: 'editing', status: 'done', screenshot: 'capture_editing.png', updated_at: null },
      ],
      connectivity: {
        status: 'running',
        result_status: null,
        result_summary: null,
        screens: [{ step: 'connectivity', label: 'validate_after_send', path: 'validate_after_send.png', taken_at: '2026-04-23T12:00:00Z' }],
      },
      recent_screens: [
        { step: 'editing', label: 'capture_editing', path: 'capture_editing.png', taken_at: '2026-04-23T12:00:00Z' },
        { step: 'connectivity', label: 'validate_after_send', path: 'validate_after_send.png', taken_at: '2026-04-23T12:00:01Z' },
      ],
    }

    renderWithProviders(<Builder />, { initialPath: '/profiles/builder' })
    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.click(await screen.findByText('Pixel 8'))
    await userEvent.click(screen.getByRole('button', { name: /Start Builder Session/ }))

    expect(await screen.findByText('Runtime Status')).toBeInTheDocument()
    expect(screen.getByText('Current Step: connectivity')).toBeInTheDocument()
    expect(screen.getAllByText('validate_after_send').length).toBeGreaterThan(0)
    expect(screen.getByText('Following Latest')).toBeInTheDocument()
    await waitFor(() => {
      expect(fetchArtifactBlobUrlMock).toHaveBeenCalledWith('pb_1', 'validate_after_send.png')
    })

    await userEvent.click(screen.getByRole('button', { name: 'Capture Editing State' }))

    expect(screen.getByText('Manual Selection')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Follow Latest' })).toBeEnabled()
    await waitFor(() => {
      expect(fetchArtifactBlobUrlMock).toHaveBeenCalledWith('pb_1', 'capture_editing.png')
    })

    await userEvent.click(screen.getByRole('button', { name: 'Capture Idle State' }))
    await waitFor(() => {
      expect(fetchArtifactBlobUrlMock).toHaveBeenCalledWith('pb_1', 'capture_idle.png')
    })
  })

  it('renders guided new session steps when strategy is enabled', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    createSessionMock.mockResolvedValue({
      id: 'pb_1', platform: 'android', device_serial: 'serial-1', name: 'qwen_android',
      status: 'draft', steps: ['idle', 'editing'], artifact_dir: '/tmp/pb_1', artifacts: [], captures: [],
    })
    configureNewSessionMock.mockResolvedValue({
      session: { id: 'pb_1', platform: 'android', device_serial: 'serial-1', name: 'qwen_android',
        status: 'draft', steps: ['idle', 'editing'], artifact_dir: '/tmp/pb_1', artifacts: [], captures: [] },
      candidates: { input_locator: [], input_focus_action: [], send_action: [], latest_bubble_match: [] },
      review_items: [], draft_profile_yaml: '', draft_mode: 'rule', requires_manual_review: true,
      applied_review_choices: {}, pending_review_fields: [], auto_review_source: 'manual',
      new_session_strategy: 'guided_tap_sequence',
      new_session_steps: [
        { step_index: 0, xml_artifact: null, screenshot_artifact: null,
          recommended_tap: { point: null, reason: null, status: 'idle' }, confirmed_tap: null, source: null },
      ],
    })

    renderWithProviders(<Builder />, { initialPath: '/profiles/builder' })
    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.click(await screen.findByText('Pixel 8'))
    await userEvent.click(screen.getByRole('button', { name: /Start Builder Session/ }))

    await userEvent.click(await screen.findByLabelText('配置多步新开对话'))
    expect(await screen.findByText('New Session Step 1')).toBeInTheDocument()
  })

  it('loads guided new session step previews from artifact downloads', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    createSessionMock.mockResolvedValue({
      id: 'pb_1', platform: 'android', device_serial: 'serial-1', name: 'qwen_android',
      status: 'draft', steps: ['idle', 'editing'], artifact_dir: '/tmp/pb_1', artifacts: [],
      captures: [],
    })
    configureNewSessionMock.mockResolvedValue({
      session: { id: 'pb_1', platform: 'android', device_serial: 'serial-1', name: 'qwen_android',
        status: 'draft', steps: ['idle', 'editing'], artifact_dir: '/tmp/pb_1', artifacts: [], captures: [] },
      candidates: { input_locator: [], input_focus_action: [], send_action: [], latest_bubble_match: [] },
      review_items: [], draft_profile_yaml: '', draft_mode: 'rule', requires_manual_review: true,
      applied_review_choices: {}, pending_review_fields: [], auto_review_source: 'manual',
      new_session_strategy: 'guided_tap_sequence',
      new_session_steps: [
        { step_index: 0, xml_artifact: null, screenshot_artifact: 'new_session_step_0.png',
          recommended_tap: { point: null, reason: null, status: 'idle' }, confirmed_tap: null, source: null },
      ],
    })

    renderWithProviders(<Builder />, { initialPath: '/profiles/builder' })
    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.click(await screen.findByText('Pixel 8'))
    await userEvent.click(screen.getByRole('button', { name: /Start Builder Session/ }))

    await userEvent.click(await screen.findByLabelText('配置多步新开对话'))
    await waitFor(() => {
      expect(fetchArtifactBlobUrlMock).toHaveBeenCalledWith('pb_1', 'new_session_step_0.png')
    })

    const preview = await screen.findByLabelText('New Session Step 1 preview')
    const img = within(preview).getByRole('img', { name: 'step 1 screenshot' })
    expect(img).toHaveAttribute('src', 'blob:new_session_step_0.png')
  })

  it('shows unavailable when VLM is missing', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    useVlmMock.mockImplementation(
      () => ({ data: { base_url: null, model: null, api_key: null } } as never),
    )
    createSessionMock.mockResolvedValue({
      id: 'pb_1', platform: 'android', device_serial: 'serial-1', name: 'qwen_android',
      status: 'draft', steps: ['idle', 'editing'], artifact_dir: '/tmp/pb_1', artifacts: [], captures: [],
    })
    configureNewSessionMock.mockResolvedValue({
      session: { id: 'pb_1', platform: 'android', device_serial: 'serial-1', name: 'qwen_android',
        status: 'draft', steps: ['idle', 'editing'], artifact_dir: '/tmp/pb_1', artifacts: [], captures: [] },
      candidates: { input_locator: [], input_focus_action: [], send_action: [], latest_bubble_match: [] },
      review_items: [], draft_profile_yaml: '', draft_mode: 'rule', requires_manual_review: true,
      applied_review_choices: {}, pending_review_fields: [], auto_review_source: 'manual',
      new_session_strategy: 'guided_tap_sequence',
      new_session_steps: [
        { step_index: 0, xml_artifact: 'new_session_step_0.xml', screenshot_artifact: 'new_session_step_0.png',
          recommended_tap: { point: null, reason: null, status: 'unavailable', error: 'vlm_unavailable' },
          recommendation_error: 'vlm_unavailable', confirmed_tap: null, source: null },
      ],
    })

    renderWithProviders(<Builder />, { initialPath: '/profiles/builder' })
    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.click(await screen.findByText('Pixel 8'))
    await userEvent.click(screen.getByRole('button', { name: /Start Builder Session/ }))

    await userEvent.click(await screen.findByLabelText('配置多步新开对话'))

    expect(await screen.findByText('当前未配置 VLM，仅支持人工点选')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '接受推荐' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '重新点选' })).toBeEnabled()
  })

  it('shows provider failure reason for new session recommendations', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    createSessionMock.mockResolvedValue({
      id: 'pb_1', platform: 'android', device_serial: 'serial-1', name: 'qwen_android',
      status: 'draft', steps: ['idle', 'editing'], artifact_dir: '/tmp/pb_1', artifacts: [], captures: [],
    })
    configureNewSessionMock.mockResolvedValue({
      session: { id: 'pb_1', platform: 'android', device_serial: 'serial-1', name: 'qwen_android',
        status: 'draft', steps: ['idle', 'editing'], artifact_dir: '/tmp/pb_1', artifacts: [], captures: [] },
      candidates: { input_locator: [], input_focus_action: [], send_action: [], latest_bubble_match: [] },
      review_items: [], draft_profile_yaml: '', draft_mode: 'rule', requires_manual_review: true,
      applied_review_choices: {}, pending_review_fields: [], auto_review_source: 'manual',
      new_session_strategy: 'guided_tap_sequence',
      new_session_steps: [
        { step_index: 0, xml_artifact: 'new_session_step_0.xml', screenshot_artifact: 'new_session_step_0.png',
          recommended_tap: { point: null, reason: null, status: 'failed', error: 'auth_error' },
          recommendation_error: 'auth_error', confirmed_tap: null, source: null },
      ],
    })

    renderWithProviders(<Builder />, { initialPath: '/profiles/builder' })
    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.click(await screen.findByText('Pixel 8'))
    await userEvent.click(screen.getByRole('button', { name: /Start Builder Session/ }))

    await userEvent.click(await screen.findByLabelText('配置多步新开对话'))

    expect(await screen.findByText('推荐请求失败：认证失败')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '接受推荐' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '重新点选' })).toBeEnabled()
  })

  it('shows image capability failures for new session recommendations', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    createSessionMock.mockResolvedValue({
      id: 'pb_1', platform: 'android', device_serial: 'serial-1', name: 'qwen_android',
      status: 'draft', steps: ['idle', 'editing'], artifact_dir: '/tmp/pb_1', artifacts: [], captures: [],
    })
    configureNewSessionMock.mockResolvedValue({
      session: { id: 'pb_1', platform: 'android', device_serial: 'serial-1', name: 'qwen_android',
        status: 'draft', steps: ['idle', 'editing'], artifact_dir: '/tmp/pb_1', artifacts: [], captures: [] },
      candidates: { input_locator: [], input_focus_action: [], send_action: [], latest_bubble_match: [] },
      review_items: [], draft_profile_yaml: '', draft_mode: 'rule', requires_manual_review: true,
      applied_review_choices: {}, pending_review_fields: [], auto_review_source: 'manual',
      new_session_strategy: 'guided_tap_sequence',
      new_session_steps: [
        { step_index: 0, xml_artifact: 'new_session_step_0.xml', screenshot_artifact: 'new_session_step_0.png',
          recommended_tap: { point: null, reason: null, status: 'failed', error: 'image_input_unsupported' },
          recommendation_error: 'image_input_unsupported', confirmed_tap: null, source: null },
      ],
    })

    renderWithProviders(<Builder />, { initialPath: '/profiles/builder' })
    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.click(await screen.findByText('Pixel 8'))
    await userEvent.click(screen.getByRole('button', { name: /Start Builder Session/ }))

    await userEvent.click(await screen.findByLabelText('配置多步新开对话'))

    expect(await screen.findByText('推荐请求失败：模型不支持图像输入')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '接受推荐' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '重新点选' })).toBeEnabled()
  })

  it('shows unknown recommendation failures without English fallback text', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    createSessionMock.mockResolvedValue({
      id: 'pb_1', platform: 'android', device_serial: 'serial-1', name: 'qwen_android',
      status: 'draft', steps: ['idle', 'editing'], artifact_dir: '/tmp/pb_1', artifacts: [], captures: [],
    })
    configureNewSessionMock.mockResolvedValue({
      session: { id: 'pb_1', platform: 'android', device_serial: 'serial-1', name: 'qwen_android',
        status: 'draft', steps: ['idle', 'editing'], artifact_dir: '/tmp/pb_1', artifacts: [], captures: [] },
      candidates: { input_locator: [], input_focus_action: [], send_action: [], latest_bubble_match: [] },
      review_items: [], draft_profile_yaml: '', draft_mode: 'rule', requires_manual_review: true,
      applied_review_choices: {}, pending_review_fields: [], auto_review_source: 'manual',
      new_session_strategy: 'guided_tap_sequence',
      new_session_steps: [
        { step_index: 0, xml_artifact: 'new_session_step_0.xml', screenshot_artifact: 'new_session_step_0.png',
          recommended_tap: { point: null, reason: null, status: 'failed', error: null },
          recommendation_error: null, confirmed_tap: null, source: null },
      ],
    })

    renderWithProviders(<Builder />, { initialPath: '/profiles/builder' })
    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.click(await screen.findByText('Pixel 8'))
    await userEvent.click(screen.getByRole('button', { name: /Start Builder Session/ }))

    await userEvent.click(await screen.findByLabelText('配置多步新开对话'))

    expect(await screen.findByText('推荐请求失败：未知错误')).toBeInTheDocument()
    expect(screen.queryByText('推荐请求失败：unknown')).not.toBeInTheDocument()
  })

  it('accepts the recommended tap for one step', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    createSessionMock.mockResolvedValue({
      id: 'pb_1', platform: 'android', device_serial: 'serial-1', name: 'qwen_android',
      status: 'draft', steps: ['idle', 'editing'], artifact_dir: '/tmp/pb_1', artifacts: [], captures: [],
    })
    const draftWithRecommendation = {
      session: { id: 'pb_1', platform: 'android', device_serial: 'serial-1', name: 'qwen_android',
        status: 'draft', steps: ['idle', 'editing'], artifact_dir: '/tmp/pb_1', artifacts: [], captures: [] },
      candidates: { input_locator: [], input_focus_action: [], send_action: [], latest_bubble_match: [] },
      review_items: [], draft_profile_yaml: '', draft_mode: 'rule', requires_manual_review: true,
      applied_review_choices: {}, pending_review_fields: [], auto_review_source: 'manual',
      new_session_strategy: 'guided_tap_sequence',
      new_session_steps: [
        { step_index: 0, xml_artifact: null, screenshot_artifact: null,
          recommended_tap: { point: { x: 111, y: 222 }, reason: 'start chat', status: 'ready' },
          confirmed_tap: null, source: null },
      ],
    }
    configureNewSessionMock.mockResolvedValue(draftWithRecommendation)
    confirmNewSessionStepMock.mockResolvedValue({ ...draftWithRecommendation,
      new_session_steps: [
        { step_index: 0, xml_artifact: null, screenshot_artifact: null,
          recommended_tap: { point: { x: 111, y: 222 }, reason: 'start chat', status: 'ready' },
          confirmed_tap: { x: 111, y: 222 }, source: 'recommended' },
      ],
    })

    renderWithProviders(<Builder />, { initialPath: '/profiles/builder' })
    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.click(await screen.findByText('Pixel 8'))
    await userEvent.click(screen.getByRole('button', { name: /Start Builder Session/ }))

    await userEvent.click(await screen.findByLabelText('配置多步新开对话'))
    await userEvent.click(await screen.findByRole('button', { name: '接受推荐' }))

    expect(confirmNewSessionStepMock).toHaveBeenCalledWith({
      sessionId: 'pb_1', stepIndex: 0, x: 111, y: 222, source: 'recommended',
    })
  })

  it('renders the recommended point marker on the step preview', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    createSessionMock.mockResolvedValue({
      id: 'pb_1', platform: 'android', device_serial: 'serial-1', name: 'qwen_android',
      status: 'draft', steps: ['idle', 'editing'], artifact_dir: '/tmp/pb_1', artifacts: [], captures: [],
    })
    configureNewSessionMock.mockResolvedValue({
      session: { id: 'pb_1', platform: 'android', device_serial: 'serial-1', name: 'qwen_android',
        status: 'draft', steps: ['idle', 'editing'], artifact_dir: '/tmp/pb_1', artifacts: [], captures: [] },
      candidates: { input_locator: [], input_focus_action: [], send_action: [], latest_bubble_match: [] },
      review_items: [], draft_profile_yaml: '', draft_mode: 'rule', requires_manual_review: true,
      applied_review_choices: {}, pending_review_fields: [], auto_review_source: 'manual',
      new_session_strategy: 'guided_tap_sequence',
      new_session_steps: [
        { step_index: 0, xml_artifact: 'new_session_step_0.xml', screenshot_artifact: 'new_session_step_0.png',
          recommended_tap: { point: { x: 111, y: 222 }, reason: 'start chat', status: 'ready' },
          confirmed_tap: null, source: null },
      ],
    })

    renderWithProviders(<Builder />, { initialPath: '/profiles/builder' })
    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.click(await screen.findByText('Pixel 8'))
    await userEvent.click(screen.getByRole('button', { name: /Start Builder Session/ }))

    await userEvent.click(await screen.findByLabelText('配置多步新开对话'))

    const img = await screen.findByRole('img', { name: 'step 1 screenshot' })
    Object.defineProperty(img, 'naturalWidth', { configurable: true, value: 1080 })
    Object.defineProperty(img, 'naturalHeight', { configurable: true, value: 2400 })
    fireEvent.load(img)

    expect(await screen.findByLabelText('New Session Step 1 recommended point')).toBeInTheDocument()
  })

  it('allows manual override on the step image', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    createSessionMock.mockResolvedValue({
      id: 'pb_1', platform: 'android', device_serial: 'serial-1', name: 'qwen_android',
      status: 'draft', steps: ['idle', 'editing'], artifact_dir: '/tmp/pb_1', artifacts: [], captures: [],
    })
    const baseDraft = {
      session: { id: 'pb_1', platform: 'android', device_serial: 'serial-1', name: 'qwen_android',
        status: 'draft', steps: ['idle', 'editing'], artifact_dir: '/tmp/pb_1', artifacts: [], captures: [] },
      candidates: { input_locator: [], input_focus_action: [], send_action: [], latest_bubble_match: [] },
      review_items: [], draft_profile_yaml: '', draft_mode: 'rule', requires_manual_review: true,
      applied_review_choices: {}, pending_review_fields: [], auto_review_source: 'manual',
      new_session_strategy: 'guided_tap_sequence',
      new_session_steps: [
        { step_index: 0, xml_artifact: null, screenshot_artifact: 'new_session_step_0.png',
          recommended_tap: { point: null, reason: null, status: 'failed' }, confirmed_tap: null, source: null },
      ],
    }
    configureNewSessionMock.mockResolvedValue(baseDraft)
    confirmNewSessionStepMock.mockResolvedValue({
      ...baseDraft,
      new_session_steps: [
        { step_index: 0, xml_artifact: null, screenshot_artifact: 'new_session_step_0.png',
          recommended_tap: { point: null, reason: null, status: 'failed' },
          confirmed_tap: { x: 300, y: 500 }, source: 'manual' },
      ],
    })

    renderWithProviders(<Builder />, { initialPath: '/profiles/builder' })
    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.click(await screen.findByText('Pixel 8'))
    await userEvent.click(screen.getByRole('button', { name: /Start Builder Session/ }))

    await userEvent.click(await screen.findByLabelText('配置多步新开对话'))
    await userEvent.click(await screen.findByRole('button', { name: '重新点选' }))

    const stepPreview = await screen.findByLabelText('New Session Step 1 preview')
    await act(async () => {
      fireEvent.click(stepPreview, { clientX: 300, clientY: 500 })
    })

    expect(confirmNewSessionStepMock).toHaveBeenCalledWith({
      sessionId: 'pb_1', stepIndex: 0, x: expect.any(Number), y: expect.any(Number), source: 'manual',
    })
  })

  it('updates Draft YAML after confirming all new session steps', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    createSessionMock.mockResolvedValue({
      id: 'pb_1', platform: 'android', device_serial: 'serial-1', name: 'qwen_android',
      status: 'draft', steps: ['idle', 'editing'], artifact_dir: '/tmp/pb_1', artifacts: [], captures: [],
    })
    const draftWithRecommendation = {
      session: { id: 'pb_1', platform: 'android', device_serial: 'serial-1', name: 'qwen_android',
        status: 'draft', steps: ['idle', 'editing'], artifact_dir: '/tmp/pb_1', artifacts: [], captures: [] },
      candidates: { input_locator: [], input_focus_action: [], send_action: [], latest_bubble_match: [] },
      review_items: [], draft_mode: 'rule', requires_manual_review: true,
      applied_review_choices: {}, pending_review_fields: [], auto_review_source: 'manual',
      new_session_strategy: 'guided_tap_sequence',
      new_session_steps: [
        { step_index: 0, xml_artifact: null, screenshot_artifact: null,
          recommended_tap: { point: { x: 111, y: 222 }, reason: 'start chat', status: 'ready' },
          confirmed_tap: null, source: null },
      ],
      draft_profile_yaml: 'new_session_action:\n- action: tap_xy\n  x: 111\n  y: 222\n',
    }
    configureNewSessionMock.mockResolvedValue(draftWithRecommendation)
    confirmNewSessionStepMock.mockResolvedValue({
      ...draftWithRecommendation,
      new_session_steps: [
        { step_index: 0, xml_artifact: null, screenshot_artifact: null,
          recommended_tap: { point: { x: 111, y: 222 }, reason: 'start chat', status: 'ready' },
          confirmed_tap: { x: 111, y: 222 }, source: 'recommended' },
      ],
      draft_profile_yaml: 'new_session_action:\n- action: tap_xy\n  x: 111\n  y: 222\n',
    })

    renderWithProviders(<Builder />, { initialPath: '/profiles/builder' })
    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.click(await screen.findByText('Pixel 8'))
    await userEvent.click(screen.getByRole('button', { name: /Start Builder Session/ }))

    await userEvent.click(await screen.findByLabelText('配置多步新开对话'))
    await userEvent.click(await screen.findByRole('button', { name: '接受推荐' }))

    await waitFor(() => {
      const textarea = screen.queryAllByRole('textbox').find(
        (el) => el.getAttribute('value')?.includes('new_session_action:') ||
                 el.textContent?.includes('new_session_action:')
      )
      expect(textarea ?? screen.getByText(/new_session_action:/)).toBeInTheDocument()
    })
  })

  it('configures guided new session step count before capture', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    createSessionMock.mockResolvedValue({
      id: 'pb_1',
      platform: 'android',
      device_serial: 'serial-1',
      name: 'qwen_android',
      status: 'draft',
      steps: ['idle', 'editing'],
      artifact_dir: '/tmp/pb_1',
      artifacts: [],
      captures: [],
    })
    configureNewSessionMock.mockResolvedValue({
      session: { id: 'pb_1', platform: 'android', device_serial: 'serial-1', name: 'qwen_android',
        status: 'draft', steps: ['idle', 'editing'], artifact_dir: '/tmp/pb_1', artifacts: [], captures: [] },
      candidates: { input_locator: [], input_focus_action: [], send_action: [], latest_bubble_match: [] },
      review_items: [],
      draft_profile_yaml: '',
      draft_mode: 'rule',
      requires_manual_review: true,
      applied_review_choices: {},
      pending_review_fields: [],
      auto_review_source: 'manual',
      new_session_strategy: 'guided_tap_sequence',
      new_session_steps: [
        { step_index: 0, xml_artifact: null, screenshot_artifact: null,
          recommended_tap: { point: null, reason: null, status: 'idle' }, confirmed_tap: null, source: null },
        { step_index: 1, xml_artifact: null, screenshot_artifact: null,
          recommended_tap: { point: null, reason: null, status: 'idle' }, confirmed_tap: null, source: null },
      ],
    })

    renderWithProviders(<Builder />, { initialPath: '/profiles/builder' })
    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.click(await screen.findByText('Pixel 8'))
    await userEvent.click(screen.getByRole('button', { name: /Start Builder Session/ }))

    await userEvent.click(await screen.findByLabelText('配置多步新开对话'))
    await userEvent.click(screen.getByLabelText('Step Count 2'))

    expect(configureNewSessionMock).toHaveBeenCalledWith({
      sessionId: 'pb_1',
      strategy: 'guided_tap_sequence',
      stepCount: 2,
    })
  })
})
