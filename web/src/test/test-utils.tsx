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
  queryClient?: QueryClient
}

export function renderWithProviders(
  ui: ReactElement,
  opts: WrapperOpts = {},
  rtlOpts?: RenderOptions,
) {
  const queryClient = opts.queryClient ?? createTestQueryClient()

  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <ConfigProvider>
        <AntdApp>
          <MemoryRouter initialEntries={[opts.initialPath ?? '/']}>{children}</MemoryRouter>
        </AntdApp>
      </ConfigProvider>
    </QueryClientProvider>
  )

  return render(ui, { wrapper: Wrapper, ...rtlOpts })
}
