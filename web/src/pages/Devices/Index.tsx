import { Button, Card, Empty, Space, Table, Tag, Typography } from 'antd'

import { useDevices, useRefreshDevices } from '../../api/devices'
import { Device } from '../../types/api'

export function DevicesPage() {
  const devices = useDevices()
  const refresh = useRefreshDevices()

  return (
    <Card
      title="Devices"
      extra={
        <Button loading={refresh.isPending} onClick={() => refresh.mutateAsync()}>
          Refresh
        </Button>
      }
    >
      {!devices.data?.length && !devices.isLoading ? (
        <Empty description="No devices" />
      ) : (
        <Table<Device>
          rowKey="serial"
          loading={devices.isLoading}
          dataSource={devices.data ?? []}
          pagination={false}
          columns={[
            {
              title: 'Serial',
              dataIndex: 'serial',
            },
            {
              title: 'Label',
              render: (_, row) =>
                row.label ?? <Typography.Text type="secondary">-</Typography.Text>,
            },
            {
              title: 'Model',
              dataIndex: 'model',
            },
            {
              title: 'Android',
              dataIndex: 'android_version',
            },
            {
              title: 'Status',
              render: (_, row) => (
                <Space>
                  <Tag color={row.online ? 'green' : 'default'}>
                    {row.online ? 'online' : 'offline'}
                  </Tag>
                  <Tag color={row.enabled ? 'blue' : 'red'}>
                    {row.enabled ? 'enabled' : 'disabled'}
                  </Tag>
                </Space>
              ),
            },
          ]}
        />
      )}
    </Card>
  )
}
