import {
  AppstoreOutlined,
  CompassOutlined,
  ControlOutlined,
  DashboardOutlined,
  ExperimentOutlined,
  FileSearchOutlined,
  FileTextOutlined,
  HeartOutlined,
  LogoutOutlined,
  MobileOutlined,
  SettingOutlined,
  ThunderboltOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import { Badge, Button, Layout, Menu, Space, Typography } from 'antd'
import type { MenuProps } from 'antd'
import { useMemo } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { logoutApi } from '../api/auth'
import { useAnomalyCount } from '../api/anomalies'
import { useBatchStats } from '../api/batches'
import { useUpdateStatus } from '../api/system'
import { useAuth } from '../hooks/useAuth'
import { CommandPalette } from './CommandPalette'
import { ThemeToggle } from './ThemeToggle'

const { Header, Sider, Content } = Layout

interface NavItem {
  key: string
  label: string
  icon: React.ReactNode
  match?: (path: string) => boolean
}

interface NavGroup {
  key: string
  label: string
  items: NavItem[]
}

const NAV: NavGroup[] = [
  {
    key: 'home',
    label: '首页',
    items: [
      {
        key: '/',
        label: 'Dashboard',
        icon: <DashboardOutlined />,
        match: (p) => p === '/',
      },
    ],
  },
  {
    key: 'work',
    label: '任务',
    items: [
      {
        key: '/tests/quick',
        label: '单次测试',
        icon: <ThunderboltOutlined />,
      },
      {
        key: '/batches',
        label: '批次 Batches',
        icon: <ExperimentOutlined />,
      },
    ],
  },
  {
    key: 'resources',
    label: '资源',
    items: [
      {
        key: '/devices',
        label: '设备 Devices',
        icon: <MobileOutlined />,
      },
      {
        key: '/profiles',
        label: '配置档 Profiles',
        icon: <FileTextOutlined />,
        // Profiles edit/new live under /profiles/* but builder routes are siblings.
        match: (p) =>
          p === '/profiles' ||
          (p.startsWith('/profiles/') &&
            !p.startsWith('/profiles/health') &&
            !p.startsWith('/profiles/builder') &&
            !p.startsWith('/profiles/web-builder')),
      },
      {
        key: '/profiles/health',
        label: 'Profile 健康 Health',
        icon: <HeartOutlined />,
      },
      {
        key: '/profiles/builder',
        label: '配置档构建器',
        icon: <CompassOutlined />,
        match: (p) =>
          p.startsWith('/profiles/builder') || p.startsWith('/profiles/web-builder'),
      },
    ],
  },
  {
    key: 'system',
    label: '系统',
    items: [
      {
        key: '/config',
        label: '设置 Config',
        icon: <SettingOutlined />,
      },
      {
        key: '/system/logs',
        label: '运行日志 Logs',
        icon: <FileSearchOutlined />,
      },
      {
        key: '/system/anomalies',
        label: '异常中心 Anomalies',
        icon: <WarningOutlined />,
      },
    ],
  },
]

function buildMenuItems(
  runningCount: number,
  updateAvailable: boolean,
  anomalyCount: number,
): MenuProps['items'] {
  const withBadge = (label: string, dot?: boolean) => (
    <Space size={8}>
      <span>{label}</span>
      {dot ? <Badge dot style={{ boxShadow: 'none' }} /> : null}
    </Space>
  )
  return NAV.map((group) => ({
    key: group.key,
    type: 'group',
    label: group.label,
    children: group.items.map((item) => {
      let label: React.ReactNode = item.label
      // Surface in-flight batches as a count badge on the Batches entry, and a
      // dot on Config when a code update is available — both visible from any page.
      if (item.key === '/batches' && runningCount > 0) {
        label = (
          <Space size={8}>
            <span>{item.label}</span>
            <Badge count={runningCount} size="small" style={{ boxShadow: 'none' }} />
          </Space>
        )
      } else if (item.key === '/config' && updateAvailable) {
        label = withBadge(item.label, true)
      } else if (item.key === '/system/anomalies' && anomalyCount > 0) {
        label = (
          <Space size={8}>
            <span>{item.label}</span>
            <Badge count={anomalyCount} size="small" style={{ boxShadow: 'none' }} />
          </Space>
        )
      }
      return { key: item.key, icon: item.icon, label }
    }),
  }))
}

function findActiveKey(path: string): string {
  for (const group of NAV) {
    for (const item of group.items) {
      const matched = item.match ? item.match(path) : path.startsWith(item.key)
      if (matched) return item.key
    }
  }
  return '/'
}

export function AppLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const { logout } = useAuth()

  const stats = useBatchStats()
  const runningCount = (stats.data?.running ?? 0) + (stats.data?.queued ?? 0)
  const update = useUpdateStatus()
  const updateAvailable = !!update.data?.enabled && update.data?.up_to_date === false
  const anomalyCount = useAnomalyCount().data ?? 0
  const items = useMemo(
    () => buildMenuItems(runningCount, updateAvailable, anomalyCount),
    [runningCount, updateAvailable, anomalyCount],
  )
  const selected = useMemo(() => [findActiveKey(location.pathname)], [location.pathname])

  const onLogout = async () => {
    await logoutApi()
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider width={232} style={{ borderRight: '1px solid var(--aa-border)' }}>
        <div
          style={{
            padding: '18px 18px 12px',
            color: 'rgba(255,255,255,0.92)',
            display: 'flex',
            alignItems: 'center',
            gap: 10,
          }}
        >
          <div
            style={{
              width: 26,
              height: 26,
              borderRadius: 6,
              background:
                'linear-gradient(135deg, var(--aa-cobalt) 0%, #6486FF 100%)',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 4px 14px rgba(37,71,208,0.45)',
            }}
          >
            <AppstoreOutlined style={{ color: '#fff', fontSize: 14 }} />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.15 }}>
            <span style={{ fontSize: 13, fontWeight: 600, letterSpacing: 0.2 }}>
              AutoAgent Test
            </span>
            <span
              style={{
                fontSize: 11,
                color: 'rgba(255,255,255,0.42)',
                fontFamily: 'var(--aa-mono)',
              }}
            >
              v0.4
            </span>
          </div>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={selected}
          items={items}
          onClick={({ key }) => navigate(key)}
          style={{ borderInlineEnd: 0, marginTop: 4 }}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            background: 'var(--aa-surface)',
            paddingInline: 20,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            borderBottom: '1px solid var(--aa-border)',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              color: 'var(--aa-text-muted)',
              fontSize: 12,
            }}
          >
            <ControlOutlined />
            <span>按 </span>
            <span className="aa-kbd">⌘</span>
            <span className="aa-kbd">K</span>
            <span> 打开命令面板</span>
          </div>
          <Space size={10}>
            <ThemeToggle />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              admin
            </Typography.Text>
            <Button size="small" icon={<LogoutOutlined />} onClick={onLogout}>
              登出
            </Button>
          </Space>
        </Header>
        <Content style={{ padding: '20px 24px' }}>
          <Outlet />
        </Content>
      </Layout>
      <CommandPalette />
    </Layout>
  )
}
