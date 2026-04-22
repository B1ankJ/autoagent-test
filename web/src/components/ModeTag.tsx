import { Tag } from 'antd'
import { Mode } from '../types/api'

const COLORS: Record<Mode, string> = {
  api: 'blue',
  web: 'purple',
  android: 'green',
}

export function ModeTag({ mode }: { mode: Mode }) {
  return <Tag color={COLORS[mode]}>{mode}</Tag>
}
