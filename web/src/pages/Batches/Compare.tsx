import { ArrowLeftOutlined } from '@ant-design/icons'
import { Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useMemo } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useBatch } from '../../api/batches'
import { DiffText } from '../../components/DiffText'
import { ErrorState } from '../../components/states/ErrorState'
import { PageHeader } from '../../components/states/PageHeader'
import { PageSkeleton } from '../../components/states/PageSkeleton'
import { buildBatchComparison, type SampleComparisonRow } from '../../utils/batchComparison'
import { formatDurationMs } from '../../utils/duration'

function DurationCell({ ms }: { ms?: number }) {
  if (ms === undefined) return <span className="aa-mono">-</span>
  return (
    <span className="aa-mono" style={{ fontVariantNumeric: 'tabular-nums' }}>
      {formatDurationMs(ms)}
    </span>
  )
}

/** Δ = B − A. Positive (B slower) is rendered danger-red, negative (B
 * faster) success-green — a directional convention specific to this column,
 * distinct from Batches List's magnitude-only anomaly highlight. */
function DeltaCell({ row }: { row: SampleComparisonRow }) {
  if (!row.a || !row.b || row.a.durationMs === undefined || row.b.durationMs === undefined) {
    return <span className="aa-mono">-</span>
  }
  const delta = row.b.durationMs - row.a.durationMs
  if (delta === 0) return <span className="aa-mono">0</span>
  const sign = delta > 0 ? '+' : '-'
  return (
    <Typography.Text
      type={delta > 0 ? 'danger' : 'success'}
      className="aa-mono"
      style={{ fontVariantNumeric: 'tabular-nums' }}
    >
      {sign}
      {formatDurationMs(Math.abs(delta))}
    </Typography.Text>
  )
}

export function Compare() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const aId = params.get('a') ?? undefined
  const bId = params.get('b') ?? undefined

  const aQ = useBatch(aId)
  const bQ = useBatch(bId)

  const comparison = useMemo(() => {
    if (!aQ.data || !bQ.data) return null
    return buildBatchComparison(aQ.data.samples, bQ.data.samples)
  }, [aQ.data, bQ.data])

  const breadcrumb = (
    <a onClick={() => navigate('/batches')} style={{ color: 'var(--aa-text-muted)' }}>
      <ArrowLeftOutlined /> 批次
    </a>
  )

  if (!aId || !bId) {
    return (
      <div>
        <PageHeader eyebrow={breadcrumb} title="批次对比" />
        <ErrorState
          title="需要选择两个批次"
          description="请从批次列表勾选恰好两个批次后再点击对比。"
          onRetry={() => navigate('/batches')}
          retryLabel="返回批次列表"
        />
      </div>
    )
  }

  if (aQ.isError || bQ.isError) {
    const err = (aQ.error ?? bQ.error) as Error | undefined
    return (
      <div>
        <PageHeader eyebrow={breadcrumb} title="批次对比" />
        <ErrorState
          title="批次加载失败"
          description="其中一个批次无法加载,可能已被删除或清理。"
          detail={err?.message}
          onRetry={() => {
            aQ.refetch()
            bQ.refetch()
          }}
        />
      </div>
    )
  }

  if (!aQ.data || !bQ.data || !comparison) {
    return (
      <div>
        <PageHeader eyebrow={breadcrumb} title="批次对比" />
        <PageSkeleton rows={6} table />
      </div>
    )
  }

  const columns: ColumnsType<SampleComparisonRow> = [
    {
      title: 'Sample ID',
      dataIndex: 'sampleId',
      key: 'sampleId',
      render: (value: string, row) => (
        <Space size={6}>
          <span className="aa-mono">{value}</span>
          {!row.a ? <Tag color="blue">仅 B 存在</Tag> : null}
          {!row.b ? <Tag color="orange">仅 A 存在</Tag> : null}
        </Space>
      ),
    },
    {
      title: '耗时 A',
      key: 'durationA',
      width: 120,
      render: (_v, row) => <DurationCell ms={row.a?.durationMs} />,
    },
    {
      title: '耗时 B',
      key: 'durationB',
      width: 120,
      render: (_v, row) => <DurationCell ms={row.b?.durationMs} />,
    },
    {
      title: 'Δ',
      key: 'delta',
      width: 120,
      render: (_v, row) => <DeltaCell row={row} />,
    },
  ]

  return (
    <div>
      <PageHeader
        eyebrow={breadcrumb}
        title="批次对比"
        subtitle={
          <Space size={8} wrap>
            <a onClick={() => navigate(`/batches/${aQ.data!.batch_id}`)}>
              A: <span>{aQ.data.name}</span>
            </a>
            <span style={{ color: 'var(--aa-text-muted)' }}>vs</span>
            <a onClick={() => navigate(`/batches/${bQ.data!.batch_id}`)}>
              B: <span>{bQ.data.name}</span>
            </a>
          </Space>
        }
      />

      <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
        {comparison.commonCount} 个共同 sample · {comparison.onlyACount} 个仅 A ·{' '}
        {comparison.onlyBCount} 个仅 B
      </Typography.Paragraph>

      <Table<SampleComparisonRow>
        rowKey="sampleId"
        size="small"
        dataSource={comparison.rows}
        columns={columns}
        pagination={false}
        expandable={{
          rowExpandable: (row) => !!row.a && !!row.b,
          expandedRowRender: (row) =>
            row.a && row.b ? (
              <DiffText before={row.a.effectiveResponse} after={row.b.effectiveResponse} />
            ) : null,
        }}
        locale={{ emptyText: '这两个批次没有共同的 sample id' }}
      />
    </div>
  )
}
