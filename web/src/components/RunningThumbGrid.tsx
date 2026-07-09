import { PictureOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { Skeleton, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'
import { listScreenshots, screenshotUrl } from '../api/screenshots'
import { Sample } from '../types/api'

const THUMB_W = 96
const THUMB_H = 140
const THUMB_FETCH_W = THUMB_W * 2
// Live samples move fast enough that a few-second lag is fine, but polling
// every sample on every tick would be chatty — this keeps it light while
// still feeling "live".
const POLL_MS = 3000

interface CardProps {
  batchId: string
  sample: Sample
  onClick: () => void
}

function RunningThumbCard({ batchId, sample, onClick }: CardProps) {
  const shots = useQuery({
    queryKey: ['screenshots', batchId, sample.id],
    queryFn: () => listScreenshots(batchId, sample.id),
    refetchInterval: POLL_MS,
  })

  const latest = shots.data && shots.data.length > 0 ? shots.data[shots.data.length - 1] : null

  return (
    <div
      onClick={onClick}
      style={{
        width: THUMB_W,
        cursor: 'pointer',
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
      }}
    >
      <div
        style={{
          width: THUMB_W,
          height: THUMB_H,
          borderRadius: 6,
          overflow: 'hidden',
          background: 'var(--aa-surface-alt)',
          border: '1px solid var(--aa-border)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        {shots.isLoading ? (
          <Skeleton.Image active style={{ width: THUMB_W, height: THUMB_H }} />
        ) : latest && !latest.is_sensitive ? (
          <img
            src={screenshotUrl(batchId, sample.id, latest.name, THUMB_FETCH_W)}
            alt={latest.label}
            width={THUMB_W}
            height={THUMB_H}
            style={{ objectFit: 'cover' }}
          />
        ) : (
          <PictureOutlined style={{ fontSize: 18, color: 'var(--aa-text-muted)' }} />
        )}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
        <Typography.Text
          className="aa-mono"
          style={{ fontSize: 10.5 }}
          ellipsis={{ tooltip: sample.id }}
        >
          {sample.id}
        </Typography.Text>
        {sample.device_serial ? (
          <Typography.Text
            type="secondary"
            className="aa-mono"
            style={{ fontSize: 10 }}
            ellipsis={{ tooltip: sample.device_serial }}
          >
            {sample.device_serial}
          </Typography.Text>
        ) : null}
      </div>
    </div>
  )
}

interface Props {
  batchId: string
  samples: Sample[]
}

/** Live thumbnail wall for a batch's currently-running samples, so you can
 * see where every in-flight run is at without opening each sample. */
export function RunningThumbGrid({ batchId, samples }: Props) {
  const navigate = useNavigate()
  const running = samples.filter((s) => s.status === 'running')

  if (running.length === 0) return null

  return (
    <div
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: 12,
        padding: '12px 0',
      }}
    >
      {running.map((sample) => (
        <RunningThumbCard
          key={sample.id}
          batchId={batchId}
          sample={sample}
          onClick={() =>
            navigate(`/batches/${batchId}/samples/${encodeURIComponent(sample.id)}`)
          }
        />
      ))}
    </div>
  )
}
