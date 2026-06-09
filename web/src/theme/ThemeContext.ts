import { createContext } from 'react'

export type ThemeMode = 'system' | 'light' | 'dark'
export type ResolvedMode = 'light' | 'dark'

export interface ThemeContextValue {
  mode: ThemeMode
  resolved: ResolvedMode
  setMode: (mode: ThemeMode) => void
}

export const ThemeContext = createContext<ThemeContextValue | null>(null)
