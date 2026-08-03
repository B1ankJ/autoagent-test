import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'
import { FailureClusterPanel } from './FailureClusterPanel'
import type { Sample } from '../types/api'

function failedSample(id: string, error: string): Sample {
  return { id, prompts: ['x'], mode: 'api', target_profile: 'p', status: 'failed', error }
}

it('renders nothing with fewer than 2 failed samples', () => {
  const samples = [failedSample('s1', 'device offline: emulator-5554')]
  const { container } = render(
    <FailureClusterPanel samples={samples} activeClusterId={null} onSelectCluster={vi.fn()} />,
  )
  expect(container).toBeEmptyDOMElement()
})

it('renders one row per cluster with its count, sorted by count descending', async () => {
  const samples = [
    failedSample('s1', 'timeout 1000ms'),
    failedSample('s2', 'device offline: emulator-5554'),
    failedSample('s3', 'device offline: emulator-5556'),
  ]
  render(<FailureClusterPanel samples={samples} activeClusterId={null} onSelectCluster={vi.fn()} />)

  // Collapsed by default — open it to see the group rows.
  await userEvent.click(screen.getByText(/错误分组/))
  expect(screen.getByText('device offline: <DEVICE>')).toBeInTheDocument()
  expect(screen.getByText('2')).toBeInTheDocument()
  expect(screen.getByText('device offline: emulator-5554')).toBeInTheDocument()
})

it('calls onSelectCluster with the pattern id when 筛选 is clicked, and null when clicked again', async () => {
  const samples = [
    failedSample('s1', 'device offline: emulator-5554'),
    failedSample('s2', 'device offline: emulator-5556'),
  ]
  const onSelectCluster = vi.fn()
  const { rerender } = render(
    <FailureClusterPanel samples={samples} activeClusterId={null} onSelectCluster={onSelectCluster} />,
  )
  await userEvent.click(screen.getByText(/错误分组/))
  await userEvent.click(screen.getByRole('button', { name: /筛\s?选/ }))
  expect(onSelectCluster).toHaveBeenCalledWith('device offline: <DEVICE>')

  rerender(
    <FailureClusterPanel
      samples={samples}
      activeClusterId="device offline: <DEVICE>"
      onSelectCluster={onSelectCluster}
    />,
  )
  await userEvent.click(screen.getByRole('button', { name: /取消筛选/ }))
  expect(onSelectCluster).toHaveBeenCalledWith(null)
})
