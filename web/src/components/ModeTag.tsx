import { Tag } from 'antd'
import { ProfilePlatform } from '../types/api'

const COLORS: Record<ProfilePlatform, string> = {
  api: 'blue',
  web: 'purple',
  android: 'green',
}

export function ModeTag({ mode }: { mode: ProfilePlatform }) {
  return <Tag color={COLORS[mode]}>{mode}</Tag>
}
