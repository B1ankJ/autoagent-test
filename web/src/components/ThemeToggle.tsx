import { DesktopOutlined, MoonOutlined, SunOutlined } from '@ant-design/icons'
import { Dropdown, type MenuProps, Tooltip } from 'antd'
import type { ThemeMode } from '../theme/ThemeContext'
import { useTheme } from '../theme/useTheme'

const ICONS: Record<ThemeMode, React.ReactNode> = {
  light: <SunOutlined />,
  dark: <MoonOutlined />,
  system: <DesktopOutlined />,
}

const LABELS: Record<ThemeMode, string> = {
  light: '亮色',
  dark: '暗色',
  system: '跟随系统',
}

export function ThemeToggle() {
  const { mode, resolved, setMode } = useTheme()

  const items: MenuProps['items'] = (['system', 'light', 'dark'] as ThemeMode[]).map((key) => ({
    key,
    icon: ICONS[key],
    label: LABELS[key],
  }))

  return (
    <Dropdown
      menu={{
        items,
        selectable: true,
        selectedKeys: [mode],
        onClick: ({ key }) => setMode(key as ThemeMode),
      }}
      trigger={['click']}
      placement="bottomRight"
    >
      <Tooltip title={`主题 · ${LABELS[mode]}（当前 ${resolved === 'dark' ? '暗' : '亮'}）`}>
        <button
          type="button"
          aria-label="切换主题"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: 32,
            height: 32,
            border: '1px solid var(--aa-border)',
            background: 'var(--aa-surface)',
            color: 'var(--aa-text)',
            borderRadius: 6,
            cursor: 'pointer',
            transition: 'border-color 120ms ease, background 120ms ease',
          }}
        >
          {ICONS[mode]}
        </button>
      </Tooltip>
    </Dropdown>
  )
}
