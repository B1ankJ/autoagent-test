import { Tag } from 'antd'
import { ExecutionMode, ProfilePlatform } from '../types/api'

type ModeValue = ExecutionMode | ProfilePlatform

const COLORS: Record<ModeValue, string> = {
  api: 'blue',
  web: 'purple',
  android: 'green',
  gui_pc_web: 'purple',
  gui_android: 'green',
  agent_pc: 'cyan',
  agent_android: 'geekblue',
}

const LABELS: Record<ModeValue, string> = {
  api: 'api',
  web: 'web',
  android: 'android',
  gui_pc_web: 'gui_pc_web',
  gui_android: 'gui_android',
  agent_pc: 'agent_pc',
  agent_android: 'agent_android',
}

export function ModeTag({ mode }: { mode: ModeValue }) {
  return <Tag color={COLORS[mode]}>{LABELS[mode]}</Tag>
}
