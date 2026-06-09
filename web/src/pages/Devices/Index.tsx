import { MobileOutlined, ReloadOutlined } from '@ant-design/icons'
import { Button, Space, Table, Tag, Typography } from 'antd'
import { useState } from 'react'

import {
  useDevices,
  useDisableIme,
  useEnableIme,
  useInstallAdbKeyboard,
  useRefreshDevices,
} from '../../api/devices'
import { DeviceStreamModal } from '../../components/DeviceStreamModal'
import { EmptyState } from '../../components/states/EmptyState'
import { PageHeader } from '../../components/states/PageHeader'
import { Device } from '../../types/api'

export function DevicesPage() {
  const devices = useDevices()
  const refresh = useRefreshDevices()
  const installAdbKeyboard = useInstallAdbKeyboard()
  const enableIme = useEnableIme()
  const disableIme = useDisableIme()
  const [streamSerial, setStreamSerial] = useState<string | null>(null)

  const rows = devices.data ?? []
  const onlineCount = rows.filter((d) => d.online).length

  return (
    <div>
      <DeviceStreamModal serial={streamSerial} onClose={() => setStreamSerial(null)} />
      <PageHeader
        eyebrow="资源"
        title="设备 Devices"
        subtitle={
          rows.length > 0
            ? `共 ${rows.length} 台,在线 ${onlineCount}`
            : 'ADB 可见的设备列表与 IME 状态'
        }
        extra={
          <Button
            icon={<ReloadOutlined />}
            loading={refresh.isPending}
            onClick={() => refresh.mutateAsync()}
          >
            刷新
          </Button>
        }
      />
      {rows.length === 0 && !devices.isLoading ? (
        <EmptyState
          icon={<MobileOutlined />}
          title="没有可用设备"
          description="检查 USB 连接 / adb 授权,再点刷新。"
          action={
            <Button
              type="primary"
              icon={<ReloadOutlined />}
              loading={refresh.isPending}
              onClick={() => refresh.mutateAsync()}
            >
              重新探测
            </Button>
          }
        />
      ) : (
        <Table<Device>
          rowKey="serial"
          size="small"
          loading={devices.isLoading}
          dataSource={rows}
          pagination={false}
          columns={[
            {
              title: 'Serial',
              dataIndex: 'serial',
              render: (value: string) => <span className="aa-mono">{value}</span>,
            },
            {
              title: '别名',
              render: (_, row) =>
                row.label ?? <Typography.Text type="secondary">-</Typography.Text>,
            },
            {
              title: '型号',
              dataIndex: 'model',
              render: (value?: string) =>
                value ? <span className="aa-mono aa-muted">{value}</span> : '-',
            },
            {
              title: 'Android',
              dataIndex: 'android_version',
              width: 88,
            },
            {
              title: '状态',
              width: 170,
              render: (_, row) => (
                <Space size={4}>
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
              width: 220,
              render: (_, row) => (
                <Space size={4} wrap>
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
              title: '操作',
              render: (_, row) => (
                <Space size={4} wrap>
                  <Button
                    size="small"
                    disabled={!row.online}
                    onClick={() => setStreamSerial(row.serial)}
                  >
                    查看画面
                  </Button>
                  <Button
                    size="small"
                    disabled={!row.online || row.adb_keyboard_installed === true}
                    loading={installAdbKeyboard.isPending}
                    onClick={() => installAdbKeyboard.mutateAsync(row.serial)}
                  >
                    Install ADB Keyboard
                  </Button>
                  {row.adb_keyboard_installed &&
                    (row.adb_keyboard_enabled ? (
                      <Button
                        size="small"
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
                    ))}
                </Space>
              ),
            },
          ]}
        />
      )}
    </div>
  )
}
