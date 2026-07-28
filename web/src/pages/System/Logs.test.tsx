import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'

import { renderWithProviders } from '../../test/test-utils'
import { LogsPage } from './Logs'

const { mockUseAppLog, mockDownloadAppLog } = vi.hoisted(() => ({
  mockUseAppLog: vi.fn(),
  mockDownloadAppLog: vi.fn(),
}))

vi.mock('../../api/system', () => ({
  useAppLog: mockUseAppLog,
  downloadAppLog: mockDownloadAppLog,
}))

// LogViewer wraps real Monaco, which doesn't run in jsdom — stub it with a
// plain element that exposes what the page actually needs to verify:
// the tailed content, and a way to trigger onMount so scroll-to-bottom
// wiring can be exercised.
vi.mock('../../components/LogViewer', () => ({
  LogViewer: ({ value, onMount }: { value: string; onMount?: (editor: unknown) => void }) => {
    const revealLine = vi.fn()
    onMount?.({ getModel: () => ({ getLineCount: () => 3 }), revealLine })
    return <pre data-testid="log-content">{value}</pre>
  },
}))

beforeEach(() => {
  vi.clearAllMocks()
})

it('shows an empty state when the log file does not exist yet', async () => {
  mockUseAppLog.mockReturnValue({
    data: { path: '/app/logs/uvicorn.log', exists: false, size_bytes: 0, truncated: false, content: '' },
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
    isFetching: false,
  })
  renderWithProviders(<LogsPage />)
  expect(await screen.findByText('尚未找到日志文件')).toBeInTheDocument()
  expect(screen.getByText(/\/app\/logs\/uvicorn\.log/)).toBeInTheDocument()
})

it('shows an error state and retries on demand', async () => {
  const refetch = vi.fn()
  mockUseAppLog.mockReturnValue({
    data: undefined,
    isLoading: false,
    isError: true,
    error: new Error('network down'),
    refetch,
    isFetching: false,
  })
  const user = userEvent.setup()
  renderWithProviders(<LogsPage />)

  expect(await screen.findByText('日志加载失败')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: /重\s?试/ }))
  expect(refetch).toHaveBeenCalled()
})

it('renders the tailed log content and lets the user change the line count', async () => {
  const user = userEvent.setup()
  mockUseAppLog.mockReturnValue({
    data: {
      path: '/app/logs/uvicorn.log',
      exists: true,
      size_bytes: 2048,
      truncated: true,
      content: 'line 1\nline 2',
    },
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
    isFetching: false,
  })
  renderWithProviders(<LogsPage />)

  // toHaveTextContent normalizes internal whitespace/newlines to a single space.
  expect(await screen.findByTestId('log-content')).toHaveTextContent('line 1 line 2')
  expect(screen.getByText(/\/app\/logs\/uvicorn\.log/)).toBeInTheDocument()
  expect(screen.getByText(/仅显示末尾部分/)).toBeInTheDocument()

  // The 行数 selector calls useAppLog with the newly chosen line count.
  await user.click(screen.getByText('最近 1000 行'))
  await user.click(await screen.findByText('最近 5000 行'))
  await waitFor(() => {
    expect(mockUseAppLog).toHaveBeenLastCalledWith(5000, false)
  })
})

it('passes a refetchInterval to useAppLog only while 自动刷新 is on', async () => {
  const user = userEvent.setup()
  mockUseAppLog.mockReturnValue({
    data: { path: '/app/logs/uvicorn.log', exists: true, size_bytes: 10, truncated: false, content: 'x' },
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
    isFetching: false,
  })
  renderWithProviders(<LogsPage />)
  await screen.findByTestId('log-content')

  expect(mockUseAppLog).toHaveBeenLastCalledWith(1000, false)

  await user.click(screen.getByRole('switch'))
  await waitFor(() => {
    expect(mockUseAppLog).toHaveBeenLastCalledWith(1000, 5000)
  })
})

it('filters the displayed content by search text', async () => {
  const user = userEvent.setup()
  mockUseAppLog.mockReturnValue({
    data: {
      path: '/app/logs/uvicorn.log',
      exists: true,
      size_bytes: 10,
      truncated: false,
      content: '2026-07-28 10:00:00,000 INFO x - hello\n2026-07-28 10:00:01,000 ERROR x - boom',
    },
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
    isFetching: false,
  })
  renderWithProviders(<LogsPage />)
  expect(await screen.findByTestId('log-content')).toHaveTextContent(/hello.*boom/)

  await user.type(screen.getByPlaceholderText('搜索日志内容'), 'boom')
  await waitFor(() => {
    expect(screen.getByTestId('log-content')).not.toHaveTextContent('hello')
  })
  expect(screen.getByTestId('log-content')).toHaveTextContent('boom')
  expect(screen.getByText(/筛选后显示 1 \/ 2 行/)).toBeInTheDocument()
})

it('triggers a download of the full log file', async () => {
  const user = userEvent.setup()
  mockUseAppLog.mockReturnValue({
    data: { path: '/app/logs/uvicorn.log', exists: true, size_bytes: 10, truncated: false, content: 'x' },
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
    isFetching: false,
  })
  renderWithProviders(<LogsPage />)
  await screen.findByTestId('log-content')

  await user.click(screen.getByRole('button', { name: /下载完整日志/ }))
  expect(mockDownloadAppLog).toHaveBeenCalled()
})
