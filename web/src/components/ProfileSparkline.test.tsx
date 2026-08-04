import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { DailyPoint } from '../types/api'
import { ProfileSparkline } from './ProfileSparkline'

vi.mock('recharts', () => ({
  LineChart: ({ data, children }: { data: unknown[]; children: ReactNode }) => (
    <div data-testid="sparkline" data-points={(data as unknown[]).length}>
      {children}
    </div>
  ),
  Line: () => <div data-testid="line" />,
}))

function pt(date: string, rate: number): DailyPoint {
  return { date, success_rate: rate, avg_duration_ms: 100, sample_count: 5 }
}

describe('ProfileSparkline', () => {
  it('renders a line chart for a non-empty series', () => {
    render(<ProfileSparkline series={[pt('2026-03-01', 1), pt('2026-03-02', 0.8)]} />)
    expect(screen.getByTestId('sparkline')).toHaveAttribute('data-points', '2')
    expect(screen.getByTestId('line')).toBeInTheDocument()
  })

  it('renders nothing for an empty series', () => {
    const { container } = render(<ProfileSparkline series={[]} />)
    expect(container).toBeEmptyDOMElement()
  })
})
