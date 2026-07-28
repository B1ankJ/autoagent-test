import {
  AppstoreOutlined,
  DeleteOutlined,
  LockOutlined,
  MobileOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons'
import {
  App,
  Badge,
  Button,
  Popconfirm,
  Popover,
  Segmented,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import { useState } from 'react'

import {
  DeviceSession,
  useConnectDevice,
  useDeleteDevice,
  useDeviceSessions,
  useDevices,
  useDisableIme,
  useDisconnectDevice,
  useEnableIme,
  useInstallAdbKeyboard,
  useRefreshDevices,
  useReleaseDeviceSession,
  useUpdateDeviceLabel,
} from '../../api/devices'
import { DeviceScreenGrid } from '../../components/DeviceScreenGrid'
import { DeviceStreamModal } from '../../components/DeviceStreamModal'
import { EmptyState } from '../../components/states/EmptyState'
import { ErrorState } from '../../components/states/ErrorState'
import { PageHeader } from '../../components/states/PageHeader'
import { Device } from '../../types/api'

type ViewMode = 'table' | 'cards'
const VIEW_STORAGE_KEY = 'autoagent_devices_view'

// mm:ss — compact enough that the 剩余时间 column never wraps, unlike the
// previous "X 分 Y 秒" (which line-wrapped at the column's width in a small
// table row).
function formatRemaining(sec: number): string {
  if (sec <= 0) return '即将过期'
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

const SESSIONS_PANEL_WIDTH = 760

export function DevicesPage() {
  const devices = useDevices()
  const refresh = useRefreshDevices()
  const installAdbKeyboard = useInstallAdbKeyboard()
  const enableIme = useEnableIme()
  const disableIme = useDisableIme()
  const connectDevice = useConnectDevice()
  const disconnectDevice = useDisconnectDevice()
  const updateLabel = useUpdateDeviceLabel()
  const deleteDevice = useDeleteDevice()
  const deviceSessions = useDeviceSessions()
  const releaseSession = useReleaseDeviceSession()
  const { message } = App.useApp()
  const [streamSerial, setStreamSerial] = useState<string | null>(null)
  const [selectedSerials, setSelectedSerials] = useState<string[]>([])
  const [bulkBusy, setBulkBusy] = useState(false)
  const [releaseAllBusy, setReleaseAllBusy] = useState(false)
  const [viewMode, setViewModeState] = useState<ViewMode>(() => {
    const stored =
      typeof window !== 'undefined' ? window.localStorage.getItem(VIEW_STORAGE_KEY) : null
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

  const onToggleEnabled = async (row: Device) => {
    try {
      if (row.enabled) {
        await disconnectDevice.mutateAsync(row.serial)
        message.success('已禁用')
      } else {
        await connectDevice.mutateAsync(row.serial)
        message.success('已启用')
      }
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  const onReleaseSession = async (sessionId: string) => {
    try {
      await releaseSession.mutateAsync(sessionId)
      message.success('已释放')
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  const onReleaseAllSessions = async () => {
    const ids = (deviceSessions.data ?? []).map((s) => s.session_id)
    if (ids.length === 0) return
    setReleaseAllBusy(true)
    try {
      const results = await Promise.allSettled(ids.map((id) => releaseSession.mutateAsync(id)))
      const ok = results.filter((r) => r.status === 'fulfilled').length
      const failed = results.length - ok
      message[failed ? 'warning' : 'success'](
        `已释放 ${ok} 个会话${failed ? `,${failed} 个失败` : ''}`,
      )
    } finally {
      setReleaseAllBusy(false)
    }
  }

  // Bulk ops over the checkbox selection — same pattern as Batches List:
  // run the existing single-device endpoints in parallel, report how many
  // succeeded.
  const runBulk = async (
    verb: '启用' | '禁用' | '删除',
    fn: (serial: string) => Promise<unknown>,
  ) => {
    setBulkBusy(true)
    try {
      const results = await Promise.allSettled(selectedSerials.map((serial) => fn(serial)))
      const ok = results.filter((r) => r.status === 'fulfilled').length
      const failed = results.length - ok
      message[failed ? 'warning' : 'success'](
        `已${verb} ${ok} 台设备${failed ? `,${failed} 台失败` : ''}`,
      )
      setSelectedSerials([])
    } finally {
      setBulkBusy(false)
    }
  }

  const rows = devices.data ?? []
  const onlineCount = rows.filter((d) => d.online).length
  const sessionRows = deviceSessions.data ?? []

  const sessionsTable = (
    <Table<DeviceSession>
      rowKey="session_id"
      size="small"
      style={{ width: SESSIONS_PANEL_WIDTH }}
      loading={deviceSessions.isLoading}
      dataSource={sessionRows}
      pagination={{ pageSize: 6, size: 'small', hideOnSinglePage: true }}
      locale={{ emptyText: '当前没有正在占用设备的多轮对话' }}
      columns={[
        {
          title: 'Session ID',
          dataIndex: 'session_id',
          ellipsis: true,
          render: (value: string) => (
            <span className="aa-mono" title={value}>
              {value}
            </span>
          ),
        },
        {
          title: '占用设备',
          dataIndex: 'serial',
          width: 220,
          ellipsis: true,
          render: (serial: string) => {
            const d = rows.find((device) => device.serial === serial)
            const shown = d?.label || d?.model ? `${d.label || d.model} (${serial})` : serial
            return (
              <Tag
                className="aa-mono"
                title={shown}
                style={{
                  display: 'inline-block',
                  maxWidth: '100%',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  verticalAlign: 'bottom',
                }}
              >
                {shown}
              </Tag>
            )
          },
        },
        {
          title: '剩余时间',
          dataIndex: 'expires_in_sec',
          width: 90,
          render: (sec: number) => (
            <span className="aa-muted aa-mono" title="超过此时间未使用会自动释放">
              {formatRemaining(sec)}
            </span>
          ),
        },
        {
          title: '操作',
          width: 80,
          render: (_, row) => (
            <Popconfirm
              title="释放该会话占用的设备?"
              description="仅在确认多轮对话已结束时操作;如果对方还会继续发送请求,后续请求可能被分配到其他设备,导致对话上下文错乱。"
              okText="释放"
              okButtonProps={{ danger: true }}
              cancelText="取消"
              onConfirm={() => onReleaseSession(row.session_id)}
            >
              <Button size="small" danger loading={releaseSession.isPending}>
                释放
              </Button>
            </Popconfirm>
          ),
        },
      ]}
    />
  )

  const sessionsPopoverTitle = (
    <Space style={{ width: SESSIONS_PANEL_WIDTH, justifyContent: 'space-between' }}>
      <span>多轮对话设备占用</span>
      <Popconfirm
        title="释放全部会话占用的设备?"
        description="仅在确认所有多轮对话均已结束时操作;仍在进行中的对话,后续请求可能被分配到其他设备,导致上下文错乱。"
        okText="全部释放"
        okButtonProps={{ danger: true }}
        cancelText="取消"
        onConfirm={onReleaseAllSessions}
        disabled={releaseAllBusy}
      >
        <Button
          size="small"
          danger
          loading={releaseAllBusy}
          disabled={sessionRows.length === 0 && !releaseAllBusy}
        >
          一键释放全部
        </Button>
      </Popconfirm>
    </Space>
  )

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
            <Popover
              trigger="click"
              placement="bottomRight"
              title={sessionsPopoverTitle}
              content={sessionsTable}
            >
              <Badge count={sessionRows.length} size="small">
                <Button icon={<LockOutlined />}>会话占用</Button>
              </Badge>
            </Popover>
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
        <DeviceScreenGrid devices={rows} onOpenFullView={setStreamSerial} />
      ) : (
        <>
          {selectedSerials.length > 0 ? (
            <Space style={{ marginBottom: 12 }}>
              <Typography.Text type="secondary">已选 {selectedSerials.length} 台</Typography.Text>
              <Button
                size="small"
                icon={<PlayCircleOutlined />}
                loading={bulkBusy}
                onClick={() => runBulk('启用', (serial) => connectDevice.mutateAsync(serial))}
              >
                批量启用
              </Button>
              <Button
                size="small"
                icon={<PauseCircleOutlined />}
                loading={bulkBusy}
                onClick={() => runBulk('禁用', (serial) => disconnectDevice.mutateAsync(serial))}
              >
                批量禁用
              </Button>
              <Popconfirm
                title="批量删除设备记录"
                description="在线设备下次刷新会重新出现;离线设备记录会彻底移除。确定删除?"
                okText="删除"
                okButtonProps={{ danger: true }}
                cancelText="取消"
                onConfirm={() => runBulk('删除', (serial) => deleteDevice.mutateAsync(serial))}
              >
                <Button size="small" danger icon={<DeleteOutlined />} loading={bulkBusy}>
                  批量删除
                </Button>
              </Popconfirm>
              <a style={{ fontSize: 12 }} onClick={() => setSelectedSerials([])}>
                清除选择
              </a>
            </Space>
          ) : null}
          <Table<Device>
            rowKey="serial"
            size="small"
            loading={devices.isLoading}
            dataSource={rows}
            pagination={false}
            rowSelection={{
              selectedRowKeys: selectedSerials,
              onChange: (keys) => setSelectedSerials(keys as string[]),
              preserveSelectedRowKeys: true,
            }}
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
                    <Button
                      size="small"
                      icon={row.enabled ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
                      loading={connectDevice.isPending || disconnectDevice.isPending}
                      onClick={() => onToggleEnabled(row)}
                      title={
                        row.enabled ? '禁用后该设备不再参与批次调度' : '启用后该设备可被批次调度'
                      }
                    >
                      {row.enabled ? '禁用' : '启用'}
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
                      <Button size="small" danger icon={<DeleteOutlined />} title="删除设备记录" />
                    </Popconfirm>
                  </Space>
                ),
              },
            ]}
          />
        </>
      )}
    </div>
  )
}
