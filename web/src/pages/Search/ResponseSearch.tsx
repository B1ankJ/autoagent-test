import { Input, Select, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useProfiles } from '../../api/profiles'
import { useSampleSearch } from '../../api/search'
import { StatusTag } from '../../components/StatusTag'
import { EmptyState } from '../../components/states/EmptyState'
import { ErrorState } from '../../components/states/ErrorState'
import { PageHeader } from '../../components/states/PageHeader'
import type { SampleSearchHit } from '../../types/api'
import { splitHighlight } from '../../utils/highlight'

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
  const [draft, setDraft] = useState('')
  const [q, setQ] = useState('')
  const [profile, setProfile] = useState<string | undefined>(undefined)
  const [page, setPage] = useState(1)
  const pageSize = 20
  const profiles = useProfiles()
  const { data, isLoading, isError, refetch } = useSampleSearch({
    q,
    targetProfile: profile,
    page,
    pageSize,
  })

  const submit = (value: string) => {
    setQ(value)
    setPage(1)
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
      render: (s: string) => <Tag>{s === 'llm_response' ? 'LLM 提取' : '原始响应'}</Tag>,
    },
    { title: 'Profile', dataIndex: 'target_profile', width: 130 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (s: SampleSearchHit['status']) => <StatusTag status={s} />,
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
          onChange={(v) => {
            setProfile(v)
            setPage(1)
          }}
          options={(profiles.data ?? []).map((p) => ({ value: p.name, label: p.name }))}
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
              onChange: setPage,
              showTotal: (n) => `共 ${n} 条`,
            }}
            style={{ marginTop: 8 }}
          />
        </>
      )}
    </div>
  )
}
