import {
  AppstoreOutlined,
  DeleteOutlined,
  MobileOutlined,
  ReloadOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons'
import { App, Button, Col, Popconfirm, Row, Segmented, Space, Table, Tag, Typography } from 'antd'
import { useState } from 'react'

import {
  useDeleteDevice,
  useDevices,
  useDisableIme,
  useEnableIme,
  useInstallAdbKeyboard,
  useRefreshDevices,
  useUpdateDeviceLabel,
} from '../../api/devices'
import { DeviceStreamCard } from '../../components/DeviceStreamCard'
import { DeviceStreamModal } from '../../components/DeviceStreamModal'
import { EmptyState } from '../../components/states/EmptyState'
import { ErrorState } from '../../components/states/ErrorState'
import { PageHeader } from '../../components/states/PageHeader'
import { Device } from '../../types/api'

type ViewMode = 'table' | 'cards'
const VIEW_STORAGE_KEY = 'autoagent_devices_view'

export function DevicesPage() {
  const devices = useDevices()
  const refresh = useRefreshDevices()
  const installAdbKeyboard = useInstallAdbKeyboard()
  const enableIme = useEnableIme()
  const disableIme = useDisableIme()
  const updateLabel = useUpdateDeviceLabel()
  const deleteDevice = useDeleteDevice()
  const { message } = App.useApp()
  const [streamSerial, setStreamSerial] = useState<string | null>(null)
  const [viewMode, setViewModeState] = useState<ViewMode>(() => {
    const stored = typeof window !== 'undefined' ? window.localStorage.getItem(VIEW_STORAGE_KEY) : null
    return stored === 'cards' ? 'cards' : 'table'
  })
  const setViewMode = (next: ViewMode) => {
    setViewModeState(next)
    try {
      window.localStorage.setItem(VIEW_STORAGE_KEY, next)
    } catch {
      /* private mode etc; persistence is best-effort */
    }
  }

  const onLabelChange = async (serial: string, next: string) => {
    const trimmed = next.trim()
    try {
      await updateLabel.mutateAsync({ serial, label: trimmed === '' ? null : trimmed })
      message.success(trimmed ? '别名已更新' : '别名已清空')
    } catch (e) {
      message.error((e as Error).message)
    }
  }

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
          <Space>
            <Segmented<ViewMode>
              value={viewMode}
              onChange={(v) => setViewMode(v as ViewMode)}
              options={[
                { label: '列表', value: 'table', icon: <UnorderedListOutlined /> },
                { label: '画面', value: 'cards', icon: <AppstoreOutlined /> },
              ]}
            />
            <Button
              icon={<ReloadOutlined />}
              loading={refresh.isPending}
              onClick={() => refresh.mutateAsync()}
            >
              刷新
            </Button>
          </Space>
        }
      />
      {devices.isError ? (
        <ErrorState
          title="设备列表加载失败"
          description="可能是网络问题或后端暂时不可用。"
          detail={(devices.error as Error)?.message}
          onRetry={() => devices.refetch()}
        />
      ) : rows.length === 0 && !devices.isLoading ? (
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
      ) : viewMode === 'cards' ? (
        <Row gutter={[12, 12]}>
          {rows.map((row) => (
            <Col xs={24} sm={12} md={12} lg={8} xl={6} key={row.serial}>
              <DeviceStreamCard device={row} onOpenFullView={setStreamSerial} />
            </Col>
          ))}
        </Row>
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
              render: (_, row) => (
                <Typography.Text
                  type={row.label ? undefined : 'secondary'}
                  editable={{
                    text: row.label ?? '',
                    tooltip: '点击编辑别名',
                    onChange: (next) => {
                      if ((next ?? '') === (row.label ?? '')) return
                      onLabelChange(row.serial, next ?? '')
                    },
                  }}
                >
                  {row.label ?? '点击设置'}
                </Typography.Text>
              ),
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
                  <Popconfirm
                    title="删除该设备记录"
                    description={
                      row.online
                        ? '设备当前在线,删除后下次刷新会重新出现。确定删除?'
                        : '从列表移除这条离线设备记录。'
                    }
                    okText="删除"
                    okButtonProps={{ danger: true }}
                    cancelText="取消"
                    onConfirm={async () => {
                      try {
                        await deleteDevice.mutateAsync(row.serial)
                        message.success('已删除')
                      } catch (e) {
                        message.error((e as Error).message)
                      }
                    }}
                  >
                    <Button
                      size="small"
                      danger
                      icon={<DeleteOutlined />}
                      title="删除设备记录"
                    />
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      )}
    </div>
  )
}
