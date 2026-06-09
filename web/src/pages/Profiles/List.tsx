import {
  DeleteOutlined,
  EditOutlined,
  FileTextOutlined,
  PlusOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { App, Button, Popconfirm, Space, Table, Tabs } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useNavigate } from 'react-router-dom'
import { useDeleteProfile, useProfiles } from '../../api/profiles'
import { ModeTag } from '../../components/ModeTag'
import { EmptyState } from '../../components/states/EmptyState'
import { PageHeader } from '../../components/states/PageHeader'
import { PageSkeleton } from '../../components/states/PageSkeleton'
import { ProfileSummary } from '../../types/api'

export function ProfileList() {
  const navigate = useNavigate()
  const { data, isLoading } = useProfiles()
  const removeProfile = useDeleteProfile()
  const { message } = App.useApp()

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

  const columns: ColumnsType<ProfileSummary> = [
    { title: '名称', dataIndex: 'name' },
    {
      title: '平台',
      dataIndex: 'platform',
      width: 140,
      render: (platform: ProfileSummary['platform']) => <ModeTag mode={platform} />,
    },
    {
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
    },
  ]

  const renderTab = (rows: ProfileSummary[]) =>
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
      <Table rowKey="name" size="small" dataSource={rows} columns={columns} pagination={false} />
    )

  return (
    <div>
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
      {isLoading ? (
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
              children: renderTab(groups.android),
            },
            {
              key: 'agent_pc',
              label: `Agent PC (${groups.agent_pc.length})`,
              children: renderTab(groups.agent_pc),
            },
            {
              key: 'agent_android',
              label: `Agent Android (${groups.agent_android.length})`,
              children: renderTab(groups.agent_android),
            },
          ]}
        />
      )}
    </div>
  )
}
