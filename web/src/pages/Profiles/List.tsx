import {
  DeleteOutlined,
  DesktopOutlined,
  EditOutlined,
  FileTextOutlined,
  MobileOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { App, Button, Popconfirm, Space, Table, Tabs, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useDeleteProfile, useProfiles } from '../../api/profiles'
import { DeviceBindingModal } from '../../components/DeviceBindingModal'
import { DeviceInitModal } from '../../components/DeviceInitModal'
import { ProfileDeviceScreensModal } from '../../components/ProfileDeviceScreensModal'
import { ModeTag } from '../../components/ModeTag'
import { EmptyState } from '../../components/states/EmptyState'
import { ErrorState } from '../../components/states/ErrorState'
import { PageHeader } from '../../components/states/PageHeader'
import { PageSkeleton } from '../../components/states/PageSkeleton'
import { ProfileSummary } from '../../types/api'

export function ProfileList() {
  const navigate = useNavigate()
  const { data, isLoading, isError, error, refetch } = useProfiles()
  const removeProfile = useDeleteProfile()
  const { message } = App.useApp()
  // Which android profile's device-binding modal is open (name), + its
  // current serials to seed the checkboxes.
  const [bindTarget, setBindTarget] = useState<{ name: string; serials: string[] } | null>(null)
  const [initTarget, setInitTarget] = useState<{ name: string; serials: string[] } | null>(null)
  const [screensTarget, setScreensTarget] = useState<{ name: string; serials: string[] } | null>(
    null,
  )

  const groups = {
    api: [] as ProfileSummary[],
    web: [] as ProfileSummary[],
    android: [] as ProfileSummary[],
    agent_pc: [] as ProfileSummary[],
    agent_android: [] as ProfileSummary[],
  }
  for (const profile of data ?? []) {
    groups[profile.platform]?.push(profile)
  }
  const total = (data ?? []).length

  const makeColumns = (withDevices: boolean): ColumnsType<ProfileSummary> => {
    const cols: ColumnsType<ProfileSummary> = [
      { title: '名称', dataIndex: 'name' },
      {
        title: '平台',
        dataIndex: 'platform',
        width: 140,
        render: (platform: ProfileSummary['platform']) => <ModeTag mode={platform} />,
      },
    ]
    if (withDevices) {
      cols.push({
        title: '绑定设备',
        width: 260,
        render: (_v, row) => {
          const serials = row.serials ?? []
          return (
            <Space size={4} wrap>
              {serials.length === 0 ? (
                <Tag>任意在线设备</Tag>
              ) : (
                serials.map((s) => (
                  <Tag key={s} className="aa-mono" color="blue">
                    {s}
                  </Tag>
                ))
              )}
              <Button
                size="small"
                type="link"
                icon={<MobileOutlined />}
                onClick={() => setBindTarget({ name: row.name, serials })}
              >
                {serials.length ? '修改' : '绑定'}
              </Button>
              <Button
                size="small"
                type="link"
                icon={<PlayCircleOutlined />}
                disabled={serials.length === 0}
                title={serials.length === 0 ? '先绑定设备' : '运行初始化剧本'}
                onClick={() => setInitTarget({ name: row.name, serials })}
              >
                初始化
              </Button>
              <Button
                size="small"
                type="link"
                icon={<DesktopOutlined />}
                disabled={serials.length === 0}
                title={serials.length === 0 ? '先绑定设备' : '查看该 profile 绑定设备的实时画面'}
                onClick={() => setScreensTarget({ name: row.name, serials })}
              >
                查看画面
              </Button>
            </Space>
          )
        },
      })
    }
    cols.push({
      title: '操作',
      width: 200,
      render: (_value, row) => (
        <Space size={4}>
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => navigate(`/profiles/${row.name}`)}
          >
            编辑
          </Button>
          <Popconfirm
            title={`删除 ${row.name}?`}
            onConfirm={async () => {
              try {
                await removeProfile.mutateAsync(row.name)
                message.success('已删除')
              } catch (error) {
                message.error((error as Error).message)
              }
            }}
          >
            <Button size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    })
    return cols
  }

  const renderTab = (rows: ProfileSummary[], withDevices = false) =>
    rows.length === 0 ? (
      <EmptyState
        compact
        icon={<FileTextOutlined />}
        title="还没有配置档"
        description="新建一个 YAML,或用构建器从实机录制生成。"
        action={
          <Space size={6}>
            <Button size="small" type="primary" onClick={() => navigate('/profiles/new')}>
              新建
            </Button>
            <Button size="small" onClick={() => navigate('/profiles/builder')}>
              打开构建器
            </Button>
          </Space>
        }
      />
    ) : (
      <Table
        rowKey="name"
        size="small"
        dataSource={rows}
        columns={makeColumns(withDevices)}
        pagination={false}
      />
    )

  return (
    <div>
      <DeviceBindingModal
        profileName={bindTarget?.name ?? null}
        currentSerials={bindTarget?.serials ?? []}
        onClose={() => setBindTarget(null)}
      />
      <DeviceInitModal
        profileName={initTarget?.name ?? null}
        serials={initTarget?.serials ?? []}
        onClose={() => setInitTarget(null)}
      />
      <ProfileDeviceScreensModal
        profileName={screensTarget?.name ?? null}
        serials={screensTarget?.serials ?? []}
        onClose={() => setScreensTarget(null)}
      />
      <PageHeader
        eyebrow="资源"
        title="配置档 Profiles"
        subtitle={`共 ${total} 个 profile,按平台分组`}
        extra={
          <Space size={6}>
            <Button icon={<ThunderboltOutlined />} onClick={() => navigate('/profiles/builder')}>
              构建器
            </Button>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => navigate('/profiles/new')}
            >
              新建
            </Button>
          </Space>
        }
      />
      {isError ? (
        <ErrorState
          title="Profile 列表加载失败"
          description="可能是网络问题或后端暂时不可用。"
          detail={(error as Error)?.message}
          onRetry={() => refetch()}
        />
      ) : isLoading ? (
        <PageSkeleton table rows={3} />
      ) : (
        <Tabs
          defaultActiveKey="api"
          items={[
            { key: 'api', label: `API (${groups.api.length})`, children: renderTab(groups.api) },
            { key: 'web', label: `Web (${groups.web.length})`, children: renderTab(groups.web) },
            {
              key: 'android',
              label: `Android (${groups.android.length})`,
              children: renderTab(groups.android, true),
            },
            {
              key: 'agent_pc',
              label: `Agent PC (${groups.agent_pc.length})`,
              children: renderTab(groups.agent_pc),
            },
            {
              key: 'agent_android',
              label: `Agent Android (${groups.agent_android.length})`,
              children: renderTab(groups.agent_android, true),
            },
          ]}
        />
      )}
    </div>
  )
}
