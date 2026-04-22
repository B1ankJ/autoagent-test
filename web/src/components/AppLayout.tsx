import {
  DashboardOutlined,
  ExperimentOutlined,
  FileTextOutlined,
  LogoutOutlined,
  SettingOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { Button, Layout, Menu, Space, Typography } from 'antd'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { logoutApi } from '../api/auth'
import { useAuth } from '../hooks/useAuth'

const { Header, Sider, Content } = Layout

const menuItems = [
  { key: '/', icon: <DashboardOutlined />, label: 'Dashboard' },
  { key: '/profiles', icon: <FileTextOutlined />, label: 'Profiles' },
  { key: '/tests/quick', icon: <ThunderboltOutlined />, label: '单次测试' },
  { key: '/batches', icon: <ExperimentOutlined />, label: 'Batches' },
  { key: '/config', icon: <SettingOutlined />, label: 'Config' },
]

export function AppLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const { logout } = useAuth()

  const selected = menuItems
    .map((item) => item.key)
    .filter((key) => (key === '/' ? location.pathname === '/' : location.pathname.startsWith(key)))
    .slice(-1)

  const onLogout = async () => {
    await logoutApi()
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider width={220}>
        <div style={{ color: 'white', padding: 16, fontWeight: 600 }}>AutoAgent Test</div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={selected}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            background: '#fff',
            paddingInline: 24,
            display: 'flex',
            justifyContent: 'flex-end',
          }}
        >
          <Space>
            <Typography.Text>admin</Typography.Text>
            <Button icon={<LogoutOutlined />} onClick={onLogout}>
              登出
            </Button>
          </Space>
        </Header>
        <Content style={{ padding: 24 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
