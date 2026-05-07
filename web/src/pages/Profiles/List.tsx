import { DeleteOutlined, EditOutlined, PlusOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { App, Button, Empty, Popconfirm, Space, Table, Tabs, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useNavigate } from 'react-router-dom'
import { useDeleteProfile, useProfiles } from '../../api/profiles'
import { ModeTag } from '../../components/ModeTag'
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

  const columns: ColumnsType<ProfileSummary> = [
    { title: 'Name', dataIndex: 'name' },
    {
      title: 'Platform',
      dataIndex: 'platform',
      render: (platform: ProfileSummary['platform']) => <ModeTag mode={platform} />,
    },
    {
      title: '操作',
      render: (_value, row) => (
        <Space>
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
      <Empty description="暂无" />
    ) : (
      <Table rowKey="name" dataSource={rows} columns={columns} pagination={false} />
    )

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Space style={{ justifyContent: 'space-between', width: '100%' }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          Profiles
        </Typography.Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/profiles/new')}>
          新建
        </Button>
        <Button icon={<ThunderboltOutlined />} onClick={() => navigate('/profiles/builder')}>
          Build Profile
        </Button>
      </Space>
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
      {isLoading ? <div>加载中...</div> : null}
    </Space>
  )
}
