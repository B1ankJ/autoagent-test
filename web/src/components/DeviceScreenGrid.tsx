import { Col, Empty, Pagination, Row } from 'antd'
import { useEffect, useState } from 'react'

import type { Device } from '../types/api'
import { DeviceStreamCard } from './DeviceStreamCard'

// Each visible card opens its own websocket + H264 decoder (see
// DeviceStreamCard) — rendering every device at once doesn't scale past a
// handful (30 online devices means 30 concurrent `adb screenrecord`
// processes on the backend, which is what actually causes the timeouts,
// not just DOM weight). Paginate so only one page's worth stream live at a
// time; PAGE_SIZE_OPTIONS[0] also gates whether pagination UI shows at all.
const PAGE_SIZE_OPTIONS = [8, 12, 16, 24]
const DEFAULT_PAGE_SIZE = PAGE_SIZE_OPTIONS[0]

interface Props {
  devices: Device[]
  onOpenFullView: (serial: string) => void
}

export function DeviceScreenGrid({ devices, onOpenFullView }: Props) {
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)

  // A different device set (switched profile, list refreshed to fewer
  // devices) can leave `page` pointing past the end — reset rather than
  // render an empty page.
  useEffect(() => {
    setPage(1)
  }, [devices.length])

  if (devices.length === 0) {
    return <Empty description="没有设备" />
  }

  const start = (page - 1) * pageSize
  const paged = devices.slice(start, start + pageSize)

  return (
    <div>
      <Row gutter={[12, 12]}>
        {paged.map((device) => (
          <Col xs={24} sm={12} md={12} lg={8} xl={6} key={device.serial}>
            <DeviceStreamCard device={device} onOpenFullView={onOpenFullView} />
          </Col>
        ))}
      </Row>
      {devices.length > DEFAULT_PAGE_SIZE ? (
        <Pagination
          style={{ marginTop: 12, textAlign: 'right' }}
          current={page}
          pageSize={pageSize}
          total={devices.length}
          pageSizeOptions={PAGE_SIZE_OPTIONS.map(String)}
          showSizeChanger
          showTotal={(n) => `共 ${n} 台设备`}
          onChange={(p, ps) => {
            setPage(p)
            setPageSize(ps)
          }}
        />
      ) : null}
    </div>
  )
}
