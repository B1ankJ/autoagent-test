import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, RenderOptions } from '@testing-library/react'
import { App as AntdApp, ConfigProvider } from 'antd'
import { ReactElement, ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'

export function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  })
}

interface WrapperOpts {
  initialPath?: string
  // Full history stack + which entry is "current" — for tests that need
  // real browser-history back (navigate(-1)) to land somewhere specific,
  // e.g. asserting a "返回" link restores the previous page's querystring
  // instead of hard-navigating to a bare path. Ignored if initialPath is set.
  initialEntries?: string[]
  initialIndex?: number
  queryClient?: QueryClient
}

export function renderWithProviders(
  ui: ReactElement,
  opts: WrapperOpts = {},
  rtlOpts?: RenderOptions,
) {
  const queryClient = opts.queryClient ?? createTestQueryClient()
  const entries = opts.initialPath ? [opts.initialPath] : (opts.initialEntries ?? ['/'])

  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <ConfigProvider>
        <AntdApp>
          <MemoryRouter initialEntries={entries} initialIndex={opts.initialIndex}>
            {children}
          </MemoryRouter>
        </AntdApp>
      </ConfigProvider>
    </QueryClientProvider>
  )

  return render(ui, { wrapper: Wrapper, ...rtlOpts })
}
