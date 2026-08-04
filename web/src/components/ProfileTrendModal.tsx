import { Empty, Modal, Typography } from 'antd'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { DailyPoint } from '../types/api'

interface Props {
  profileName: string | null
  series: DailyPoint[]
  onClose: () => void
}

function Metric({
  title,
  data,
  color,
}: {
  title: string
  data: Array<{ date: string; value: number | null }>
  color: string
}) {
  return (
    <div style={{ marginBottom: 16 }}>
      <Typography.Text strong>{title}</Typography.Text>
      <ResponsiveContainer width="100%" height={140}>
        <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="date" fontSize={11} />
          <YAxis fontSize={11} width={40} />
          <Tooltip />
          <Line
            type="monotone"
            dataKey="value"
            stroke={color}
            dot={false}
            isAnimationActive={false}
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

export function ProfileTrendModal({ profileName, series, onClose }: Props) {
  return (
    <Modal
      open={!!profileName}
      title={`趋势 · ${profileName ?? ''}`}
      onCancel={onClose}
      footer={null}
      width={640}
      destroyOnClose
    >
      {series.length === 0 ? (
        <Empty description="暂无趋势数据" />
      ) : (
        <>
          <Metric
            title="成功率 (%)"
            color="#389e0d"
            data={series.map((p) => ({
              date: p.date,
              value: p.success_rate === null ? null : Math.round(p.success_rate * 100),
            }))}
          />
          <Metric
            title="平均耗时 (ms)"
            color="#d48806"
            data={series.map((p) => ({ date: p.date, value: p.avg_duration_ms }))}
          />
          <Metric
            title="样本量"
            color="#2547d0"
            data={series.map((p) => ({ date: p.date, value: p.sample_count }))}
          />
        </>
      )}
    </Modal>
  )
}

export default ProfileTrendModal
