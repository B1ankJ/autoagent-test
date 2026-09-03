import { Alert, Modal } from 'antd'
import { useState } from 'react'

import { useDevices } from '../api/devices'
import { DeviceScreenGrid } from './DeviceScreenGrid'
import { DeviceStreamModal } from './DeviceStreamModal'

interface Props {
  // profile name to show, or null when closed
  profileName: string | null
  serials: string[]
  onClose: () => void
}

/**
 * Screen-viewing grid scoped to one android / agent_android profile's bound
 * device pool, reusing the same paginated grid as the Devices page's 画面
 * view — so checking on "this profile's devices" doesn't require filtering
 * through every device on the page.
 */
export function ProfileDeviceScreensModal({ profileName, serials, onClose }: Props) {
  const devicesQ = useDevices()
  const [streamSerial, setStreamSerial] = useState<string | null>(null)

  const known = devicesQ.data ?? []
  const serialSet = new Set(serials)
  const bound = known.filter((d) => serialSet.has(d.serial))
  const missing = serials.length - bound.length

  return (
    <>
      <DeviceStreamModal serial={streamSerial} onClose={() => setStreamSerial(null)} />
      <Modal
        open={!!profileName}
        title={`设备画面 · ${profileName ?? ''}`}
        onCancel={onClose}
        footer={null}
        width={960}
        destroyOnClose
      >
        {missing > 0 ? (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 12 }}
            message={`${missing} 台绑定设备当前不在 Devices 列表中(离线太久或记录已被清理),未显示。`}
          />
        ) : null}
        <DeviceScreenGrid
          devices={bound}
          onOpenFullView={setStreamSerial}
          pausedSerial={streamSerial}
        />
      </Modal>
    </>
  )
}
