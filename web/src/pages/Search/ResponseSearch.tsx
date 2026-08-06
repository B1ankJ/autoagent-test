import { DatePicker, Input, Select, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useProfiles } from '../../api/profiles'
import { useSampleSearch } from '../../api/search'
import { StatusTag } from '../../components/StatusTag'
import { EmptyState } from '../../components/states/EmptyState'
import { ErrorState } from '../../components/states/ErrorState'
import { PageHeader } from '../../components/states/PageHeader'
import type { SampleSearchHit, SampleStatus } from '../../types/api'
import { splitHighlight } from '../../utils/highlight'

const STATUS_OPTIONS: SampleStatus[] = [
  'done',
  'failed',
  'timeout',
  'extraction_failed',
  'cancelled',
]

function Snippet({ text, term }: { text: string; term: string }) {
  return (
    <span>
      {splitHighlight(text, term).map((seg, i) =>
        seg.mark ? <mark key={i}>{seg.text}</mark> : <span key={i}>{seg.text}</span>,
      )}
    </span>
  )
}

export function ResponseSearch() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  // Search state lives in the URL so navigating into a sample and coming back
  // (browser back) restores the query/filter/page instead of clearing it.
  const q = params.get('q') ?? ''
  const profile = params.get('target_profile') ?? undefined
  const fields = params.get('fields') ?? 'all'
  const status = (params.get('status') ?? '').split(',').filter(Boolean)
  const createdAfter = params.get('created_after') ?? undefined
  const createdBefore = params.get('created_before') ?? undefined
  const page = Math.max(1, Number(params.get('page')) || 1)
  const pageSize = 20
  // `draft` is the uncommitted input text; seed it from the URL on mount so a
  // restored search shows its term in the box.
  const [draft, setDraft] = useState(() => q)
  const profiles = useProfiles()
  const { data, isLoading, isError, refetch } = useSampleSearch({
    q,
    targetProfile: profile,
    fields,
    status,
    createdAfter,
    createdBefore,
    page,
    pageSize,
  })

  const patch = (next: Record<string, string | undefined>) => {
    const merged = new URLSearchParams(params)
    for (const [k, v] of Object.entries(next)) {
      if (v) merged.set(k, v)
      else merged.delete(k)
    }
    setParams(merged, { replace: true })
  }

  const submit = (value: string) => {
    patch({ q: value.trim() || undefined, page: undefined })
  }

  const columns: ColumnsType<SampleSearchHit> = [
    {
      title: '片段',
      dataIndex: 'snippet',
      render: (snippet: string) => <Snippet text={snippet} term={q} />,
    },
    {
      title: '来源',
      dataIndex: 'source',
      width: 100,
      render: (s: string) => (
        <Tag>{s === 'prompt' ? 'Prompt' : s === 'llm_response' ? 'LLM 提取' : '原始响应'}</Tag>
      ),
    },
    { title: 'Profile', dataIndex: 'target_profile', width: 130 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (s: SampleSearchHit['status']) => <StatusTag status={s} />,
    },
    {
      title: '时间',
      dataIndex: 'ended_at',
      width: 170,
      render: (v: string | null) => (
        <span className="aa-mono" style={{ fontSize: 12 }}>
          {v ? new Date(v).toLocaleString() : '-'}
        </span>
      ),
    },
    {
      title: '操作',
      width: 90,
      render: (_v, row) => (
        <a onClick={() => navigate(`/batches/${row.batch_id}/samples/${row.sample_id}`)}>查看</a>
      ),
    },
  ]

  return (
    <div>
      <PageHeader
        eyebrow="任务"
        title="响应搜索"
        subtitle="按内容检索样本的响应(原始 + LLM 提取)"
      />
      <Space wrap style={{ marginBottom: 12 }}>
        <Input.Search
          placeholder="搜索响应内容…"
          allowClear
          style={{ width: 320 }}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onSearch={submit}
          enterButton
        />
        <Select
          allowClear
          placeholder="全部 Profile"
          style={{ width: 180 }}
          value={profile}
          onChange={(v) => patch({ target_profile: v || undefined, page: undefined })}
          options={(profiles.data ?? []).map((p) => ({ value: p.name, label: p.name }))}
        />
        <Select
          style={{ width: 130 }}
          value={fields}
          onChange={(v) => patch({ fields: v === 'all' ? undefined : v, page: undefined })}
          options={[
            { value: 'all', label: '全部字段' },
            { value: 'response', label: '仅响应' },
            { value: 'prompt', label: '仅 Prompt' },
          ]}
        />
        <Select
          mode="multiple"
          allowClear
          placeholder="全部状态"
          style={{ minWidth: 180 }}
          value={status}
          onChange={(v: string[]) =>
            patch({ status: v.length ? v.join(',') : undefined, page: undefined })
          }
          options={STATUS_OPTIONS.map((s) => ({ value: s, label: s }))}
        />
        <DatePicker.RangePicker
          showTime
          value={createdAfter && createdBefore ? [dayjs(createdAfter), dayjs(createdBefore)] : null}
          onChange={(v) =>
            patch({
              created_after: v?.[0]?.toISOString(),
              created_before: v?.[1]?.toISOString(),
              page: undefined,
            })
          }
          presets={[
            { label: '最近 24 小时', value: [dayjs().add(-24, 'h'), dayjs()] },
            { label: '最近 7 天', value: [dayjs().add(-7, 'd'), dayjs()] },
            { label: '最近 30 天', value: [dayjs().add(-30, 'd'), dayjs()] },
          ]}
        />
      </Space>
      {isError ? (
        <ErrorState title="搜索失败" onRetry={() => refetch()} />
      ) : q.trim().length < 2 ? (
        <EmptyState title="输入关键词搜索响应内容" description="至少 2 个字符。" />
      ) : !isLoading && (data?.items.length ?? 0) === 0 ? (
        <EmptyState title="没有命中" description="换个关键词试试。" />
      ) : (
        <>
          <Typography.Text type="secondary">共 {data?.total ?? 0} 条命中</Typography.Text>
          <Table<SampleSearchHit>
            rowKey={(r) => `${r.batch_id}/${r.sample_id}`}
            size="small"
            loading={isLoading}
            dataSource={data?.items ?? []}
            columns={columns}
            pagination={{
              current: page,
              pageSize,
              total: data?.total ?? 0,
              onChange: (p) => patch({ page: p > 1 ? String(p) : undefined }),
              showTotal: (n) => `共 ${n} 条`,
            }}
            style={{ marginTop: 8 }}
          />
        </>
      )}
    </div>
  )
}
