import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '../../test/test-utils'
import Builder from './Builder'

const createSessionMock = vi.fn()
const captureStepMock = vi.fn()
const generateDraftMock = vi.fn()
const applyReviewMock = vi.fn()
const validateDraftMock = vi.fn()
let runtimeMockData: unknown = null

vi.mock('../../api/profileBuilderRuntime', () => ({
  useProfileBuilderRuntime: () => ({
    data: runtimeMockData,
    isLoading: false,
  }),
  profileBuilderArtifactUrl: (_sessionId: string, name: string) => `/api/v1/mock/${name}`,
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

describe('Builder', () => {
  afterEach(() => {
    vi.clearAllMocks()
    runtimeMockData = null
  })

  it('renders guided builder steps', async () => {
    renderWithProviders(<Builder />, { initialPath: '/profiles/builder' })

    expect(await screen.findByText('Build Profile')).toBeInTheDocument()
    expect(screen.getByText('Capture Idle State')).toBeInTheDocument()
    expect(screen.getByText('Capture Editing State')).toBeInTheDocument()
    expect(screen.getByText('Capture Response State')).toBeInTheDocument()
  })

  it('creates session, captures steps, and renders draft yaml', async () => {
    createSessionMock.mockResolvedValue({
      id: 'pb_1',
      platform: 'android',
      device_serial: 'serial-1',
      name: 'qwen_android',
      status: 'draft',
      steps: ['idle', 'editing', 'response'],
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
        steps: ['idle', 'editing', 'response'],
        artifact_dir: '/tmp/pb_1',
        artifacts: ['capture_idle.xml'],
        captures: [
          {
            step: 'idle',
            package: 'com.aliyun.tongyi',
            activity: '.IdleActivity',
            xml_artifact: 'capture_idle.xml',
            screenshot_artifact: 'capture_idle.png',
          },
        ],
      })
      .mockResolvedValueOnce({
        id: 'pb_1',
        platform: 'android',
        device_serial: 'serial-1',
        name: 'qwen_android',
        status: 'draft',
        steps: ['idle', 'editing', 'response'],
        artifact_dir: '/tmp/pb_1',
        artifacts: ['capture_idle.xml', 'capture_editing.xml'],
        captures: [
          {
            step: 'idle',
            package: 'com.aliyun.tongyi',
            activity: '.IdleActivity',
            xml_artifact: 'capture_idle.xml',
            screenshot_artifact: 'capture_idle.png',
          },
          {
            step: 'editing',
            package: 'com.aliyun.tongyi',
            activity: '.EditingActivity',
            xml_artifact: 'capture_editing.xml',
            screenshot_artifact: 'capture_editing.png',
          },
        ],
      })
      .mockResolvedValueOnce({
        id: 'pb_1',
        platform: 'android',
        device_serial: 'serial-1',
        name: 'qwen_android',
        status: 'draft',
        steps: ['idle', 'editing', 'response'],
        artifact_dir: '/tmp/pb_1',
        artifacts: ['capture_idle.xml', 'capture_editing.xml', 'capture_response.xml'],
        captures: [
          {
            step: 'idle',
            package: 'com.aliyun.tongyi',
            activity: '.IdleActivity',
            xml_artifact: 'capture_idle.xml',
            screenshot_artifact: 'capture_idle.png',
          },
          {
            step: 'editing',
            package: 'com.aliyun.tongyi',
            activity: '.EditingActivity',
            xml_artifact: 'capture_editing.xml',
            screenshot_artifact: 'capture_editing.png',
          },
          {
            step: 'response',
            package: 'com.aliyun.tongyi',
            activity: '.ResponseActivity',
            xml_artifact: 'capture_response.xml',
            screenshot_artifact: 'capture_response.png',
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
        steps: ['idle', 'editing', 'response'],
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
          field: 'send_button_locator',
          reason: 'Multiple clickable controls looked like send buttons.',
          recommended_option: { type: 'xpath', value: '//*[@bounds="[909,2009][1020,2120]"]' },
          alternative_candidates: [],
          evidence_refs: [],
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
        steps: ['idle', 'editing', 'response'],
        artifact_dir: '/tmp/pb_1',
        artifacts: ['draft_profile.yaml'],
        captures: [],
      },
      draft_profile_yaml: 'name: qwen_android\nplatform: android\nsend_button_locator:\n',
    })
    validateDraftMock.mockResolvedValue({
      session: {
        id: 'pb_1',
        platform: 'android',
        device_serial: 'serial-1',
        name: 'qwen_android',
        status: 'validated',
        steps: ['idle', 'editing', 'response'],
        artifact_dir: '/tmp/pb_1',
        artifacts: ['draft_profile.yaml', 'connectivity_result.json'],
        captures: [],
      },
      draft_profile_yaml: 'name: qwen_android\nplatform: android\nsend_button_locator:\n',
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
    await userEvent.click(captureButtons[2])
    await userEvent.click(screen.getByRole('button', { name: /Generate Draft/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Apply Recommended' }))
    await userEvent.click(screen.getByRole('button', { name: /Run Connectivity Test/ }))

    await waitFor(() => {
      expect(generateDraftMock).toHaveBeenCalledWith('pb_1')
    })
    expect(applyReviewMock).toHaveBeenCalled()
    expect(validateDraftMock).toHaveBeenCalledWith('pb_1')
    expect(screen.getByDisplayValue(/name: qwen_android/)).toBeInTheDocument()
    expect(screen.getByText('Connectivity Test Result')).toBeInTheDocument()
    expect(screen.getByText('pong')).toBeInTheDocument()
  })

  it('renders runtime status and key screens when runtime data is available', async () => {
    createSessionMock.mockResolvedValue({
      id: 'pb_1',
      platform: 'android',
      device_serial: 'serial-1',
      name: 'qwen_android',
      status: 'draft',
      steps: ['idle', 'editing', 'response'],
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
        { step: 'response', status: 'done', screenshot: 'capture_response.png', updated_at: null },
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
  })
})
