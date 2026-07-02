import { App, Alert, Checkbox, Empty, Modal, Space, Tag, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { useSaveProfileDevices } from '../api/profiles'
import { useDevices } from '../api/devices'
import type { Device } from '../types/api'

interface Props {
  // profile name to bind, or null when closed
  profileName: string | null
  currentSerials: string[]
  onClose: () => void
}

function deviceLabel(d: Device): string {
  const prefix = d.label || d.model
  return prefix ? `${prefix} (${d.serial})` : d.serial
}

/**
 * Lightweight device-pool editor for an android / agent_android profile.
 * Checkboxes over the known devices; selection is PUT to the profile's
 * device binding (serials), no YAML editing required. Serials that are
 * bound but no longer present in adb are still shown (as "离线/未知") so
 * they aren't silently dropped.
 */
export function DeviceBindingModal({ profileName, currentSerials, onClose }: Props) {
  const devices = useDevices()
  const save = useSaveProfileDevices()
  const { message } = App.useApp()
  const [selected, setSelected] = useState<string[]>(currentSerials)

  // Re-seed when a different profile opens.
  useEffect(() => {
    setSelected(currentSerials)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profileName])

  const known = devices.data ?? []
  const knownSerials = new Set(known.map((d) => d.serial))
  // Bound-but-not-currently-visible serials (offline / different host).
  const orphanSerials = currentSerials.filter((s) => !knownSerials.has(s))

  const toggle = (serial: string, checked: boolean) => {
    setSelected((prev) =>
      checked ? [...new Set([...prev, serial])] : prev.filter((s) => s !== serial),
    )
  }

  const onOk = async () => {
    if (!profileName) return
    try {
      await save.mutateAsync({ name: profileName, serials: selected })
      message.success(
        selected.length === 0
          ? '已清空绑定(将使用任意在线设备)'
          : `已绑定 ${selected.length} 台设备`,
      )
      onClose()
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  return (
    <Modal
      open={!!profileName}
      title={`设备绑定 · ${profileName ?? ''}`}
      onCancel={onClose}
      onOk={onOk}
      okText="保存"
      cancelText="取消"
      confirmLoading={save.isPending}
      destroyOnClose
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="勾选多台设备即可让该 profile 并行分发到设备池。不勾选任何设备 = 使用任意在线设备。批次并发数需 ≥ 设备数才能真正并行。"
      />
      {known.length === 0 && orphanSerials.length === 0 ? (
        <Empty description="没有可用设备,请先到 Devices 页面刷新" />
      ) : (
        <Space direction="vertical" style={{ width: '100%' }} size={8}>
          {known.map((d) => (
            <Checkbox
              key={d.serial}
              checked={selected.includes(d.serial)}
              onChange={(e) => toggle(d.serial, e.target.checked)}
            >
              <Space size={6}>
                <span>{deviceLabel(d)}</span>
                <Tag color={d.online ? 'green' : 'default'}>
                  {d.online ? 'online' : 'offline'}
                </Tag>
              </Space>
            </Checkbox>
          ))}
          {orphanSerials.map((s) => (
            <Checkbox
              key={s}
              checked={selected.includes(s)}
              onChange={(e) => toggle(s, e.target.checked)}
            >
              <Space size={6}>
                <span className="aa-mono">{s}</span>
                <Tag color="orange">离线/未知</Tag>
              </Space>
            </Checkbox>
          ))}
        </Space>
      )}
      {selected.length > 0 ? (
        <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0, fontSize: 12 }}>
          已选 {selected.length} 台:{selected.join(', ')}
        </Typography.Paragraph>
      ) : null}
    </Modal>
  )
}
