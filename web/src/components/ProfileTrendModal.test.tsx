import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { DailyPoint } from '../types/api'
import { ProfileTrendModal } from './ProfileTrendModal'

vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  LineChart: ({ children }: { children: ReactNode }) => <div data-testid="chart">{children}</div>,
  Line: () => <div />,
  XAxis: () => <div />,
  YAxis: () => <div />,
  Tooltip: () => <div />,
  CartesianGrid: () => <div />,
}))

function pt(date: string): DailyPoint {
  return { date, success_rate: 0.9, avg_duration_ms: 100, sample_count: 5 }
}

describe('ProfileTrendModal', () => {
  it('renders three charts when open with a series', () => {
    render(
      <ProfileTrendModal
        profileName="qwen"
        series={[pt('2026-03-01'), pt('2026-03-02')]}
        onClose={() => {}}
      />,
    )
    expect(screen.getByText(/qwen/)).toBeInTheDocument()
    expect(screen.getAllByTestId('chart')).toHaveLength(3)
  })

  it('is not open when profileName is null', () => {
    render(<ProfileTrendModal profileName={null} series={[]} onClose={() => {}} />)
    expect(screen.queryByTestId('chart')).not.toBeInTheDocument()
  })

  it('shows an empty state for an empty series', () => {
    render(<ProfileTrendModal profileName="qwen" series={[]} onClose={() => {}} />)
    expect(screen.getByText('暂无趋势数据')).toBeInTheDocument()
  })
})
