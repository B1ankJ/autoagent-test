import { CheckCircleTwoTone, CloseCircleTwoTone, LoadingOutlined } from '@ant-design/icons'
import { Alert, App, Button, Checkbox, Empty, Modal, Space, Tag, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { useInitJob, useInitializeDevices } from '../api/profiles'

interface Props {
  // profile name to initialize, or null when closed
  profileName: string | null
  serials: string[]
  onClose: () => void
}

/**
 * Runs a profile's init playbook against the chosen devices. Kicks off an
 * async job on the backend and polls per-device status (pending → running →
 * done/failed). Optional "本次重启" overrides the profile's init_reboot for
 * this run only.
 */
export function DeviceInitModal({ profileName, serials, onClose }: Props) {
  const start = useInitializeDevices()
  const { message } = App.useApp()
  const [selected, setSelected] = useState<string[]>(serials)
  const [reboot, setReboot] = useState(false)
  const [jobId, setJobId] = useState<string | null>(null)
  const job = useInitJob(jobId)

  useEffect(() => {
    // Reset when reopened for a different profile.
    setSelected(serials)
    setReboot(false)
    setJobId(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profileName])

  const toggle = (serial: string, checked: boolean) =>
    setSelected((prev) => (checked ? [...new Set([...prev, serial])] : prev.filter((s) => s !== serial)))

  const onStart = async () => {
    if (!profileName || selected.length === 0) return
    try {
      const created = await start.mutateAsync({ name: profileName, serials: selected, reboot })
      setJobId(created.id)
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  const running = job.data && !job.data.finished
  const stateFor = (serial: string) => job.data?.devices.find((d) => d.serial === serial)

  return (
    <Modal
      open={!!profileName}
      title={`初始化设备 · ${profileName ?? ''}`}
      onCancel={onClose}
      footer={
        jobId ? (
          <Button onClick={onClose}>{running ? '后台继续,关闭' : '关闭'}</Button>
        ) : (
          <Space>
            <Button onClick={onClose}>取消</Button>
            <Button
              type="primary"
              loading={start.isPending}
              disabled={selected.length === 0}
              onClick={onStart}
            >
              开始初始化 ({selected.length})
            </Button>
          </Space>
        )
      }
      destroyOnClose
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="按 profile 的初始化剧本(init_action)把每台设备切换到就绪状态。勾选「本次重启」会先重启设备再跑剧本(约 +60~90s)。"
      />
      {serials.length === 0 ? (
        <Empty description="该 profile 未绑定设备,请先绑定设备" />
      ) : (
        <Space direction="vertical" style={{ width: '100%' }} size={8}>
          {serials.map((s) => {
            const st = stateFor(s)
            return (
              <div key={s} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Checkbox
                  checked={selected.includes(s)}
                  disabled={!!jobId}
                  onChange={(e) => toggle(s, e.target.checked)}
                >
                  <span className="aa-mono">{s}</span>
                </Checkbox>
                {st ? (
                  st.status === 'running' || st.status === 'pending' ? (
                    <Tag icon={<LoadingOutlined />} color="processing">
                      {st.status === 'pending' ? '排队' : '执行中'}
                    </Tag>
                  ) : st.status === 'done' ? (
                    <Tag icon={<CheckCircleTwoTone twoToneColor="#52c41a" />} color="success">
                      完成{st.rebooted ? '(已重启)' : ''} · {st.steps_run} 步 ·{' '}
                      {(st.duration_ms / 1000).toFixed(1)}s
                    </Tag>
                  ) : (
                    <Tag
                      icon={<CloseCircleTwoTone twoToneColor="#ff4d4f" />}
                      color="error"
                      title={st.error ?? ''}
                    >
                      失败: {(st.error ?? '').slice(0, 40)}
                    </Tag>
                  )
                ) : null}
              </div>
            )
          })}
        </Space>
      )}
      {!jobId && serials.length > 0 ? (
        <Checkbox
          checked={reboot}
          onChange={(e) => setReboot(e.target.checked)}
          style={{ marginTop: 12 }}
        >
          本次先重启设备(覆盖 profile 设置)
        </Checkbox>
      ) : null}
      {job.data?.finished ? (
        <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0, fontSize: 12 }}>
          全部完成:成功 {job.data.devices.filter((d) => d.status === 'done').length} / 失败{' '}
          {job.data.devices.filter((d) => d.status === 'failed').length}
        </Typography.Paragraph>
      ) : null}
    </Modal>
  )
}
