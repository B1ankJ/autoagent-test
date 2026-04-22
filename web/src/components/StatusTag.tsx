import { Tag } from 'antd'
import { BatchStatus, SampleStatus } from '../types/api'

const COLORS: Record<BatchStatus | SampleStatus, string> = {
  queued: 'default',
  running: 'blue',
  done: 'green',
  failed: 'red',
  timeout: 'orange',
  extraction_failed: 'volcano',
  cancelled: 'orange',
}

export function StatusTag({ status }: { status: BatchStatus | SampleStatus }) {
  return <Tag color={COLORS[status] ?? 'default'}>{status}</Tag>
}
