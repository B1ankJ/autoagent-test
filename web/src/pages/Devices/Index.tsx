import { Button, Card, Empty, Space, Table, Tag, Typography } from 'antd'

import { useDevices, useDisableIme, useEnableIme, useInstallAdbKeyboard, useRefreshDevices } from '../../api/devices'
import { Device } from '../../types/api'

export function DevicesPage() {
  const devices = useDevices()
  const refresh = useRefreshDevices()
  const installAdbKeyboard = useInstallAdbKeyboard()
  const enableIme = useEnableIme()
  const disableIme = useDisableIme()

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
            {
              title: 'ADB Keyboard',
              render: (_, row) => (
                <Space>
                  <Tag color={row.adb_keyboard_installed ? 'green' : 'default'}>
                    {row.adb_keyboard_installed === null
                      ? 'install unknown'
                      : row.adb_keyboard_installed
                        ? 'installed'
                        : 'not installed'}
                  </Tag>
                  <Tag color={row.adb_keyboard_enabled ? 'blue' : 'default'}>
                    {row.adb_keyboard_enabled === null
                      ? 'ime unknown'
                      : row.adb_keyboard_enabled
                        ? 'ime enabled'
                        : 'ime disabled'}
                  </Tag>
                </Space>
              ),
            },
            {
              title: 'Actions',
              render: (_, row) => (
                <Space wrap>
                  <Button
                    size="small"
                    disabled={!row.online || row.adb_keyboard_installed === true}
                    loading={installAdbKeyboard.isPending}
                    onClick={() => installAdbKeyboard.mutateAsync(row.serial)}
                  >
                    Install ADB Keyboard
                  </Button>
                  {row.adb_keyboard_installed && (
                    <>
                      {row.adb_keyboard_enabled ? (
                        <Button
                          size="small"
                          type="default"
                          loading={disableIme.isPending}
                          onClick={() => disableIme.mutateAsync(row.serial)}
                        >
                          Disable IME
                        </Button>
                      ) : (
                        <Button
                          size="small"
                          type="primary"
                          loading={enableIme.isPending}
                          onClick={() => enableIme.mutateAsync(row.serial)}
                        >
                          Enable IME
                        </Button>
                      )}
                    </>
                  )}
                </Space>
              ),
            },
          ]}
        />
      )}
    </Card>
  )
}
