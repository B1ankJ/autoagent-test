import { screen, waitFor } from '@testing-library/react'
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

  it('passes llm draft options when enabled', async () => {
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
    })

    renderWithProviders(<Builder />, { initialPath: '/profiles/builder' })

    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.click(await screen.findByText('Pixel 8'))
    await userEvent.click(screen.getByRole('button', { name: /Start Builder Session/ }))
    await userEvent.click(await screen.findByLabelText('生成 Draft 时使用 LLM 优化'))
    await userEvent.click(await screen.findByLabelText('生成时注入 LLM 响应抽取配置'))
    await userEvent.click(screen.getByRole('button', { name: /Generate Draft/ }))

    await waitFor(() => {
      expect(generateDraftMock).toHaveBeenCalledWith({
        sessionId: 'pb_1',
        useLlmOptimization: false,
        injectLlm: true,
      })
    })
  })

  it('disables llm draft toggles when global VLM config is incomplete', async () => {
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
      expect(screen.getByLabelText('生成 Draft 时使用 LLM 优化')).toBeDisabled()
      expect(screen.getByLabelText('生成时注入 LLM 响应抽取配置')).toBeDisabled()
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
    await userEvent.click(screen.getByRole('button', { name: '查看推荐定位' }))
    await userEvent.click(screen.getByRole('button', { name: 'Apply Recommended' }))
    expect(screen.getByText('当前已应用')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Apply Recommended' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '保存/覆盖到 Profiles' }))
    await userEvent.click(screen.getByRole('button', { name: /Run Connectivity Test/ }))

    await waitFor(() => {
      expect(generateDraftMock).toHaveBeenCalledWith({
        sessionId: 'pb_1',
        useLlmOptimization: true,
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
    })

    renderWithProviders(<Builder />, { initialPath: '/profiles/builder' })

    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.click(await screen.findByText('Pixel 8'))
    await userEvent.click(screen.getByRole('button', { name: /Start Builder Session/ }))
    await userEvent.click(screen.getByRole('button', { name: /Generate Draft/ }))
    await userEvent.click(screen.getByRole('button', { name: '查看全部证据' }))

    await waitFor(() => {
      expect(fetchArtifactBlobUrlMock).toHaveBeenCalledWith('pb_1', 'capture_editing.png')
    })
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

    await userEvent.click(await screen.findByRole('button', { name: 'Apply Recommended' }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Run Connectivity Test/ })).toBeEnabled()
    })
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
    })

    renderWithProviders(<Builder />, { initialPath: '/profiles/builder' })

    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.click(await screen.findByText('Pixel 8'))
    await userEvent.click(screen.getByRole('button', { name: /Start Builder Session/ }))
    await userEvent.click(screen.getByRole('button', { name: /Generate Draft/ }))

    expect(screen.getByText(/input_locator: Multiple input candidates matched the editing capture\./)).toBeInTheDocument()
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
})
