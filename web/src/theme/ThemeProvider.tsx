import { App as AntdApp, ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { useEffect, useMemo, useState } from 'react'
import { ThemeContext, type ResolvedMode, type ThemeMode } from './ThemeContext'
import { cssVariables, darkTheme, lightTheme } from './tokens'

const STORAGE_KEY = 'autoagent_theme_mode'

function readStoredMode(): ThemeMode {
  if (typeof localStorage === 'undefined') return 'system'
  const v = localStorage.getItem(STORAGE_KEY)
  return v === 'light' || v === 'dark' || v === 'system' ? v : 'system'
}

function resolve(mode: ThemeMode): ResolvedMode {
  if (mode !== 'system') return mode
  if (typeof window === 'undefined' || !window.matchMedia) return 'light'
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function applyVariables(resolved: ResolvedMode) {
  if (typeof document === 'undefined') return
  const vars = cssVariables[resolved]
  const root = document.documentElement
  for (const [key, value] of Object.entries(vars)) {
    root.style.setProperty(key, value)
  }
  root.dataset.theme = resolved
  root.style.colorScheme = resolved
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(() => readStoredMode())
  const [resolved, setResolved] = useState<ResolvedMode>(() => resolve(readStoredMode()))

  useEffect(() => {
    const next = resolve(mode)
    setResolved(next)
    applyVariables(next)
    if (mode !== 'system') return
    const mql = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => {
      const r = mql.matches ? 'dark' : 'light'
      setResolved(r)
      applyVariables(r)
    }
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [mode])

  const setMode = (m: ThemeMode) => {
    localStorage.setItem(STORAGE_KEY, m)
    setModeState(m)
  }

  const value = useMemo(() => ({ mode, resolved, setMode }), [mode, resolved])

  return (
    <ThemeContext.Provider value={value}>
      <ConfigProvider locale={zhCN} theme={resolved === 'dark' ? darkTheme : lightTheme}>
        <AntdApp>{children}</AntdApp>
      </ConfigProvider>
    </ThemeContext.Provider>
  )
}
