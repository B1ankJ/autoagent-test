import { Line, LineChart } from 'recharts'
import type { DailyPoint } from '../types/api'

export function ProfileSparkline({ series }: { series: DailyPoint[] }) {
  if (!series || series.length === 0) return null
  const data = series.map((p) => ({
    date: p.date,
    value: p.success_rate === null ? null : Math.round(p.success_rate * 100),
  }))
  return (
    <LineChart width={72} height={22} data={data}>
      <Line
        type="monotone"
        dataKey="value"
        stroke="#389e0d"
        strokeWidth={1.5}
        dot={false}
        isAnimationActive={false}
        connectNulls
      />
    </LineChart>
  )
}

export default ProfileSparkline
