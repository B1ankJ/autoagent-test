import { AndroidOutlined, GlobalOutlined } from '@ant-design/icons'
import { Tabs } from 'antd'
import { useLocation, useNavigate } from 'react-router-dom'
import { PageHeader } from '../../components/states/PageHeader'
import AndroidBuilder from './Builder'
import WebBuilder from './WebBuilder'

type Kind = 'android' | 'web'

function inferKind(pathname: string, search: string): Kind {
  if (pathname.startsWith('/profiles/web-builder')) return 'web'
  const params = new URLSearchParams(search)
  const t = params.get('type')
  return t === 'web' ? 'web' : 'android'
}

export default function BuilderHub() {
  const navigate = useNavigate()
  const location = useLocation()
  const active = inferKind(location.pathname, location.search)

  return (
    <div>
      <PageHeader
        eyebrow="资源 / 构建器"
        title="配置档构建器"
        subtitle="录制实机操作并生成 Profile YAML;Web 与 Android 各走自己的捕获流程。"
      />
      <Tabs
        activeKey={active}
        onChange={(key) => {
          // Use the canonical /profiles/builder route with ?type=… so the
          // browser back button keeps producing sensible URLs.
          navigate(`/profiles/builder?type=${key}`)
        }}
        items={[
          {
            key: 'android',
            label: (
              <span>
                <AndroidOutlined /> Android
              </span>
            ),
            children: <AndroidBuilder />,
          },
          {
            key: 'web',
            label: (
              <span>
                <GlobalOutlined /> Web
              </span>
            ),
            children: <WebBuilder />,
          },
        ]}
      />
    </div>
  )
}
