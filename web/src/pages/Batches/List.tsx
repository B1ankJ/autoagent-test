import {
  DeleteOutlined,
  ExperimentOutlined,
  EyeOutlined,
  FilterOutlined,
  LinkOutlined,
  PlusOutlined,
  SettingOutlined,
  StopOutlined,
} from '@ant-design/icons'
import {
  App,
  Badge,
  Button,
  Checkbox,
  DatePicker,
  Dropdown,
  Input,
  Popconfirm,
  Popover,
  Select,
  Space,
  Switch,
  Table,
  Tag,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs, { type Dayjs } from 'dayjs'
import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  useBatches,
  useBatchStats,
  useCancelActiveBatches,
  useCancelBatch,
  useDeleteBatch,
  useDeleteBatchesByStatus,
} from '../../api/batches'
import { useDevices } from '../../api/devices'
import { useProfiles } from '../../api/profiles'
import { BatchPromptModal } from '../../components/BatchPromptModal'
import { DeviceStreamModal } from '../../components/DeviceStreamModal'
import { ModeTag } from '../../components/ModeTag'
import { SessionConversationModal } from '../../components/SessionConversationModal'
import { StatusTag } from '../../components/StatusTag'
import { EmptyState } from '../../components/states/EmptyState'
import { ErrorState } from '../../components/states/ErrorState'
import { PageHeader } from '../../components/states/PageHeader'
import { useResizableColumns } from '../../hooks/useResizableColumns'
import { BatchStatus, BatchSummary, ExecutionMode } from '../../types/api'
import { formatDurationMs } from '../../utils/duration'

// Filter state is mirrored to the URL query so refresh / share / back-button
// all retain the user's view. Keys are intentionally short to keep URLs scannable.
const QP_Q = 'q'
const QP_STATUS = 'status'
const QP_MODE = 'mode'
const QP_PAGE = 'page'
const QP_SIZE = 'size'
const QP_FROM = 'from'   // ISO string, inclusive lower bound on Batch.created_at
const QP_TO = 'to'       // ISO string, inclusive upper bound on Batch.created_at
const QP_PROFILE = 'profile' // target_profile_default exact match
const QP_DEVICE = 'device'   // device_serial substring on sample.metadata_json
const QP_EMPTY = 'empty'     // "1" = only show total=1 done batches with empty response
const QP_HIDE_END_SESSION = 'hide_end_session' // "1" = hide Sample.end_session=true no-ops
const QP_DURATION_ANOMALY = 'duration_anomaly' // "1" = only show duration-anomalous batches

// Column visibility: 名称/操作 always show; these can be hidden and the
// choice is remembered per browser so different people can trim the table to
// what they care about (device-heavy vs. timing-heavy workflows differ).
const TOGGLEABLE_COLUMNS = [
  { key: 'mode', label: '模式' },
  { key: 'profile_device', label: 'Profile / 设备' },
  { key: 'response', label: '响应(单条)' },
  { key: 'status', label: '状态' },
  { key: 'progress', label: '进度' },
  { key: 'duration', label: '耗时' },
  { key: 'started_at', label: '开始时间' },
] as const

const COLUMN_VISIBILITY_KEY = 'autoagent_batches_visible_columns'

function loadVisibleColumns(): Set<string> {
  const all = new Set(TOGGLEABLE_COLUMNS.map((c) => c.key))
  try {
    const raw = localStorage.getItem(COLUMN_VISIBILITY_KEY)
    if (!raw) return all
    const arr = JSON.parse(raw) as string[]
    if (!Array.isArray(arr)) return all
    // Ignore stale keys from an older column set; unknown keys are dropped.
    return new Set(arr.filter((k) => TOGGLEABLE_COLUMNS.some((c) => c.key === k)))
  } catch {
    return all
  }
}

export function BatchList() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { message } = App.useApp()
  const cancelActive = useCancelActiveBatches()
  const cancelOne = useCancelBatch()
  const deleteOne = useDeleteBatch()
  const deleteByStatus = useDeleteBatchesByStatus()
  const [previewBatchId, setPreviewBatchId] = useState<string | null>(null)
  const [conversationSessionId, setConversationSessionId] = useState<string | null>(null)
  const [streamSerial, setStreamSerial] = useState<string | null>(null)
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [bulkBusy, setBulkBusy] = useState(false)
  const [visibleCols, setVisibleCols] = useState<Set<string>>(() => loadVisibleColumns())
  const toggleCol = (key: string) => {
    setVisibleCols((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      localStorage.setItem(COLUMN_VISIBILITY_KEY, JSON.stringify([...next]))
      return next
    })
  }

  const page = Math.max(1, parseInt(searchParams.get(QP_PAGE) ?? '1', 10) || 1)
  const pageSize = parseInt(searchParams.get(QP_SIZE) ?? '20', 10) || 20
  const debouncedQ = searchParams.get(QP_Q) ?? ''
  const rawStatus = searchParams.get(QP_STATUS)
  const statusFilter: BatchStatus[] = rawStatus
    ? (rawStatus.split(',').filter(Boolean) as BatchStatus[])
    : []
  const rawMode = searchParams.get(QP_MODE)
  const modeFilter: ExecutionMode[] = rawMode
    ? (rawMode.split(',').filter(Boolean) as ExecutionMode[])
    : []
  const fromIso = searchParams.get(QP_FROM) || undefined
  const toIso = searchParams.get(QP_TO) || undefined
  const dateRange: [Dayjs | null, Dayjs | null] = [
    fromIso ? dayjs(fromIso) : null,
    toIso ? dayjs(toIso) : null,
  ]
  const profileFilter = searchParams.get(QP_PROFILE) || undefined
  const deviceFilter = searchParams.get(QP_DEVICE) || undefined
  const emptyResponseOnly = searchParams.get(QP_EMPTY) === '1'
  const hideEndSession = searchParams.get(QP_HIDE_END_SESSION) === '1'
  const durationAnomalyOnly = searchParams.get(QP_DURATION_ANOMALY) === '1'

  const profilesQ = useProfiles()
  const devicesQ = useDevices()

  // Local-only input mirror so typing doesn't trigger a URL/query write on
  // every keystroke; commit to URL after a 300ms debounce.
  const [searchInput, setSearchInput] = useState(debouncedQ)

  // Apply multiple param changes in ONE navigate. Back-to-back
  // setSearchParams() calls race because each reads the URL fresh, so the
  // second navigate silently overwrites the first — losing fields.
  const updateParams = (changes: Record<string, string | undefined>) => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        for (const [key, value] of Object.entries(changes)) {
          if (value === undefined || value === '') next.delete(key)
          else next.set(key, value)
        }
        return next
      },
      { replace: true },
    )
  }
  const setStatusFilter = (v: BatchStatus[]) => {
    updateParams({ [QP_STATUS]: v.length ? v.join(',') : undefined, [QP_PAGE]: undefined })
  }
  const setModeFilter = (v: ExecutionMode[]) => {
    updateParams({ [QP_MODE]: v.length ? v.join(',') : undefined, [QP_PAGE]: undefined })
  }
  const setPagination = (p: number, ps: number) => {
    updateParams({
      [QP_PAGE]: p === 1 ? undefined : String(p),
      [QP_SIZE]: ps === 20 ? undefined : String(ps),
    })
  }
  const setProfileFilter = (v: string | undefined) => {
    updateParams({ [QP_PROFILE]: v, [QP_PAGE]: undefined })
  }
  const setDeviceFilter = (v: string | undefined) => {
    updateParams({ [QP_DEVICE]: v, [QP_PAGE]: undefined })
  }
  const setEmptyResponseOnly = (v: boolean) => {
    updateParams({ [QP_EMPTY]: v ? '1' : undefined, [QP_PAGE]: undefined })
  }
  const setHideEndSession = (v: boolean) => {
    updateParams({ [QP_HIDE_END_SESSION]: v ? '1' : undefined, [QP_PAGE]: undefined })
  }
  const setDurationAnomalyOnly = (v: boolean) => {
    updateParams({ [QP_DURATION_ANOMALY]: v ? '1' : undefined, [QP_PAGE]: undefined })
  }
  const setDateRange = (range: [Dayjs | null, Dayjs | null] | null) => {
    const [from, to] = range ?? [null, null]
    updateParams({
      // Anchor to day boundaries so "today" picks up everything from 00:00:00.
      [QP_FROM]: from ? from.startOf('day').toISOString() : undefined,
      [QP_TO]: to ? to.endOf('day').toISOString() : undefined,
      [QP_PAGE]: undefined,
    })
  }

  useEffect(() => {
    const handle = setTimeout(() => {
      const trimmed = searchInput.trim()
      if (trimmed !== debouncedQ) {
        updateParams({ [QP_Q]: trimmed || undefined, [QP_PAGE]: undefined })
      }
    }, 300)
    return () => clearTimeout(handle)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchInput])

  const { data, isLoading, isError, error, refetch } = useBatches({
    limit: pageSize,
    offset: (page - 1) * pageSize,
    q: debouncedQ,
    createdAfter: fromIso,
    createdBefore: toIso,
    targetProfile: profileFilter,
    deviceSerial: deviceFilter,
    emptyResponseOnly,
    excludeEndSession: hideEndSession,
    durationAnomalyOnly,
    status: statusFilter,
    mode: modeFilter,
  })
  const { data: stats } = useBatchStats({
    q: debouncedQ,
    createdAfter: fromIso,
    createdBefore: toIso,
    targetProfile: profileFilter,
    deviceSerial: deviceFilter,
    emptyResponseOnly,
    excludeEndSession: hideEndSession,
    durationAnomalyOnly,
    mode: modeFilter,
  })

  // status/mode are now applied server-side (paginated correctly); no
  // client-side re-filtering needed here.
  const rows = data ?? []
  // /batches/stats groups by status rather than accepting a filter, so when
  // one or more statuses are selected the matching count is the sum of
  // those specific keys out of the breakdown rather than the grand total.
  const total = statusFilter.length
    ? statusFilter.reduce((sum, s) => sum + (stats?.[s] ?? 0), 0)
    : (stats?.total ?? 0)
  const activeCount = (stats?.queued ?? 0) + (stats?.running ?? 0)

  const onCancelActive = async () => {
    try {
      const result = await cancelActive.mutateAsync()
      const parts: string[] = []
      if (result.cancelled > 0) parts.push(`已取消 ${result.cancelled} 个进行中批次`)
      if (result.orphaned > 0) parts.push(`已清理 ${result.orphaned} 个孤儿状态`)
      message.success(parts.length ? parts.join('，') : '没有需要取消的批次')
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  const onDeleteOne = async (id: string) => {
    try {
      await deleteOne.mutateAsync(id)
      message.success('已删除')
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  const onBulkDelete = async (status: 'done' | 'failed' | 'cancelled' | 'terminal') => {
    try {
      const result = await deleteByStatus.mutateAsync(status)
      message.success(
        result.deleted > 0
          ? `已删除 ${result.deleted} 个 ${status} 批次`
          : `没有匹配 ${status} 的批次`,
      )
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  // Bulk ops over the checkbox selection. Runs the existing single-batch
  // endpoints in parallel and reports how many succeeded.
  const runBulk = async (
    verb: '取消' | '删除',
    fn: (id: string) => Promise<unknown>,
  ) => {
    setBulkBusy(true)
    try {
      const results = await Promise.allSettled(selectedIds.map((id) => fn(id)))
      const ok = results.filter((r) => r.status === 'fulfilled').length
      const failed = results.length - ok
      message[failed ? 'warning' : 'success'](
        `已${verb} ${ok} 个批次${failed ? `,${failed} 个失败` : ''}`,
      )
      setSelectedIds([])
    } finally {
      setBulkBusy(false)
    }
  }

  const columns: ColumnsType<BatchSummary> = [
    {
      title: '名称',
      dataIndex: 'name',
      render: (value: string, row) => {
        // Empty-response anomaly: single-sample batch that finished cleanly
        // (status=done) but produced no text. The backend returns "" for
        // preview_response only in this case; null means n/a.
        const isEmptyResponse =
          row.total === 1 &&
          row.status === 'done' &&
          row.preview_response !== null &&
          row.preview_response !== undefined &&
          row.preview_response === ''
        return (
          <div>
            <Space size={6}>
              <a onClick={() => navigate(`/batches/${row.batch_id}`)}>{value}</a>
              {isEmptyResponse ? (
                <Tag color="orange" title="批次完成但响应为空,可能抽取失败">
                  响应为空
                </Tag>
              ) : null}
              {row.session_id ? (
                <Tag
                  icon={<LinkOutlined />}
                  color="purple"
                  title={`该批次是多轮对话的一轮,session_id: ${row.session_id}`}
                  style={{ cursor: 'pointer' }}
                  onClick={(e) => {
                    e.stopPropagation()
                    setConversationSessionId(row.session_id ?? null)
                  }}
                >
                  多轮对话
                </Tag>
              ) : null}
              {row.is_end_session ? (
                <Tag title="Sample.end_session=true:仅释放设备会话占用,不是真实对话轮次">
                  结束会话
                </Tag>
              ) : null}
            </Space>
            {row.preview_prompt ? (
              <a
                className="aa-muted"
                title="点击查看完整 prompt 与响应"
                style={{
                  display: 'block',
                  fontSize: 12,
                  marginTop: 2,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  maxWidth: 480,
                  color: 'inherit',
                }}
                onClick={(e) => {
                  e.stopPropagation()
                  setPreviewBatchId(row.batch_id)
                }}
              >
                {row.preview_prompt}
              </a>
            ) : null}
          </div>
        )
      },
    },
    {
      key: 'mode',
      title: '模式',
      dataIndex: 'mode',
      width: 140,
      render: (mode: ExecutionMode) => <ModeTag mode={mode} />,
    },
    {
      key: 'profile_device',
      title: 'Profile / 设备',
      width: 220,
      render: (_v, row) => {
        const profiles = row.profiles ?? []
        const devices = row.devices ?? []
        if (profiles.length === 0 && devices.length === 0) {
          return <span className="aa-muted">-</span>
        }
        const chips = (
          items: string[],
          color: string,
          prefix: string,
          onItemClick?: (s: string) => void,
        ) => {
          const shown = items.slice(0, 2)
          return (
            <>
              {shown.map((s) => (
                <Tag
                  key={prefix + s}
                  color={color}
                  className="aa-mono"
                  style={{
                    marginInlineEnd: 4,
                    maxWidth: 180,
                    cursor: onItemClick ? 'pointer' : undefined,
                  }}
                  onClick={
                    onItemClick
                      ? (e) => {
                          e.stopPropagation()
                          onItemClick(s)
                        }
                      : undefined
                  }
                >
                  <span
                    style={{
                      display: 'inline-block',
                      maxWidth: 168,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                      verticalAlign: 'bottom',
                    }}
                    title={onItemClick ? `点击查看 ${s} 画面` : s}
                  >
                    {s}
                  </span>
                </Tag>
              ))}
              {items.length > 2 ? (
                <Tag title={items.join(', ')}>+{items.length - 2}</Tag>
              ) : null}
            </>
          )
        }
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {profiles.length ? <div>{chips(profiles, 'blue', 'p')}</div> : null}
            {devices.length ? <div>{chips(devices, 'default', 'd', setStreamSerial)}</div> : null}
          </div>
        )
      },
    },
    {
      key: 'response',
      title: '响应(单条)',
      width: 240,
      // Only single-sample batches carry a meaningful preview_response
      // (backend's _single_sample_preview) — it's already the effective
      // (LLM-reviewed when configured) response, same as select_effective_response
      // everywhere else, not the raw extraction.
      render: (_v, row) => {
        if (row.total !== 1 || row.preview_response === null || row.preview_response === undefined) {
          return <span className="aa-muted">-</span>
        }
        if (row.preview_response === '') {
          return <span className="aa-muted">(空)</span>
        }
        return (
          <span
            title={row.preview_response}
            style={{
              display: 'block',
              maxWidth: 224,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {row.preview_response}
          </span>
        )
      },
    },
    {
      key: 'status',
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (status: BatchStatus) => <StatusTag status={status} />,
    },
    {
      key: 'progress',
      title: '进度',
      width: 110,
      render: (_value, row) => (
        <span className="aa-mono">
          {row.done + row.failed}/{row.total}
        </span>
      ),
    },
    {
      key: 'duration',
      title: '耗时',
      width: 110,
      render: (_value, row) =>
        row.avg_duration_ms == null ? (
          <span className="aa-mono aa-muted">-</span>
        ) : (
          <span
            className="aa-mono"
            style={
              row.is_duration_anomaly
                ? { color: 'var(--aa-red, #cf1322)', fontWeight: 600 }
                : undefined
            }
            title={
              row.is_duration_anomaly
                ? '耗时明显偏离该 profile 的历史平均耗时'
                : undefined
            }
          >
            {formatDurationMs(row.avg_duration_ms)}
          </span>
        ),
    },
    {
      key: 'started_at',
      title: '开始时间',
      dataIndex: 'started_at',
      width: 200,
      render: (value?: string) => (
        <span className="aa-mono aa-muted">{value ?? '-'}</span>
      ),
    },
    {
      title: '操作',
      width: 120,
      render: (_value, row) => {
        const isActive = row.status === 'queued' || row.status === 'running'
        return (
          <Space size={0}>
            <Button
              type="text"
              size="small"
              icon={<EyeOutlined />}
              title="查看完整 prompt 与响应"
              onClick={(e) => {
                e.stopPropagation()
                setPreviewBatchId(row.batch_id)
              }}
            />
            <Popconfirm
              title="删除该批次"
              description="将一并删除 DB 记录、JSONL 结果文件和 logs 目录。不可恢复。"
              okText="删除"
              okButtonProps={{ danger: true }}
              cancelText="取消"
              disabled={isActive}
              onConfirm={(e) => {
                e?.stopPropagation()
                onDeleteOne(row.batch_id)
              }}
            >
              <Button
                type="text"
                size="small"
                danger
                icon={<DeleteOutlined />}
                disabled={isActive}
                title={isActive ? '请先取消批次再删除' : '删除批次'}
                onClick={(e) => e.stopPropagation()}
              />
            </Popconfirm>
          </Space>
        )
      },
    },
  ]

  // Columns without an explicit `key` (名称/操作) always show; the five
  // TOGGLEABLE_COLUMNS are filtered by the user's saved visibility choice.
  const visibleColumns = columns.filter((c) => {
    const key = c.key as string | undefined
    return !key || visibleCols.has(key)
  })
  const { columns: resizableColumns, components: resizableComponents } = useResizableColumns(
    visibleColumns,
    'autoagent_batches_col_widths',
  )

  // Active (non-search) filters, rendered as removable chips + counted on
  // the 筛选 button badge. Search stays on the main row.
  const activeFilters: { key: string; label: string; onClear: () => void }[] = []
  if (statusFilter.length)
    activeFilters.push({
      key: 's',
      label: `状态: ${statusFilter.join(', ')}`,
      onClear: () => setStatusFilter([]),
    })
  if (modeFilter.length)
    activeFilters.push({
      key: 'm',
      label: `模式: ${modeFilter.join(', ')}`,
      onClear: () => setModeFilter([]),
    })
  if (profileFilter)
    activeFilters.push({ key: 'p', label: `Profile: ${profileFilter}`, onClear: () => setProfileFilter(undefined) })
  if (deviceFilter)
    activeFilters.push({ key: 'd', label: `设备: ${deviceFilter}`, onClear: () => setDeviceFilter(undefined) })
  if (fromIso || toIso)
    activeFilters.push({
      key: 't',
      label: `日期: ${fromIso ? dayjs(fromIso).format('MM-DD') : '…'} ~ ${toIso ? dayjs(toIso).format('MM-DD') : '…'}`,
      onClear: () => setDateRange(null),
    })
  if (emptyResponseOnly)
    activeFilters.push({ key: 'e', label: '仅响应为空', onClear: () => setEmptyResponseOnly(false) })
  if (hideEndSession)
    activeFilters.push({
      key: 'hes',
      label: '已隐藏结束会话记录',
      onClear: () => setHideEndSession(false),
    })
  if (durationAnomalyOnly)
    activeFilters.push({
      key: 'da',
      label: '仅耗时异常',
      onClear: () => setDurationAnomalyOnly(false),
    })

  const clearAllFilters = () => {
    setStatusFilter([])
    setModeFilter([])
    setProfileFilter(undefined)
    setDeviceFilter(undefined)
    setDateRange(null)
    setEmptyResponseOnly(false)
    setHideEndSession(false)
    setDurationAnomalyOnly(false)
  }

  const filterPopover = (
    <Space direction="vertical" size={10} style={{ width: 260 }}>
      <Select
        mode="multiple"
        allowClear
        placeholder="状态(可多选)"
        style={{ width: '100%' }}
        value={statusFilter}
        onChange={setStatusFilter}
        maxTagCount="responsive"
        options={['queued', 'running', 'done', 'failed', 'cancelled'].map((status) => ({
          value: status,
          label: status,
        }))}
      />
      <Select
        mode="multiple"
        allowClear
        placeholder="模式(可多选)"
        style={{ width: '100%' }}
        value={modeFilter}
        onChange={setModeFilter}
        maxTagCount="responsive"
        options={['api', 'gui_pc_web', 'gui_android', 'agent_pc', 'agent_android'].map((mode) => ({
          value: mode,
          label: mode,
        }))}
      />
      <Select
        allowClear
        showSearch
        placeholder="Profile"
        style={{ width: '100%' }}
        value={profileFilter}
        onChange={setProfileFilter}
        loading={profilesQ.isLoading}
        options={(profilesQ.data ?? []).map((p) => ({
          value: p.name,
          label: `${p.name} (${p.platform})`,
        }))}
        filterOption={(input, option) =>
          (option?.label as string).toLowerCase().includes(input.toLowerCase())
        }
      />
      <Select
        allowClear
        showSearch
        placeholder="设备"
        style={{ width: '100%' }}
        value={deviceFilter}
        onChange={setDeviceFilter}
        loading={devicesQ.isLoading}
        options={(devicesQ.data ?? []).map((d) => ({
          value: d.serial,
          label: d.label || d.model ? `${d.label || d.model} (${d.serial})` : d.serial,
        }))}
        filterOption={(input, option) =>
          (option?.label as string).toLowerCase().includes(input.toLowerCase())
        }
      />
      <DatePicker.RangePicker
        style={{ width: '100%' }}
        value={dateRange as [Dayjs, Dayjs] | null}
        onChange={(range) => setDateRange(range as [Dayjs | null, Dayjs | null] | null)}
        allowEmpty={[true, true]}
        placeholder={['开始日期', '结束日期']}
        presets={[
          { label: '今天', value: [dayjs().startOf('day'), dayjs().endOf('day')] },
          {
            label: '最近 7 天',
            value: [dayjs().subtract(6, 'day').startOf('day'), dayjs().endOf('day')],
          },
          {
            label: '最近 30 天',
            value: [dayjs().subtract(29, 'day').startOf('day'), dayjs().endOf('day')],
          },
        ]}
      />
      <Space size={6}>
        <Switch checked={emptyResponseOnly} onChange={setEmptyResponseOnly} size="small" />
        <span style={{ fontSize: 13 }} title="只看 total=1 / done / 响应为空的批次">
          只看响应为空
        </span>
      </Space>
      <Space size={6}>
        <Switch checked={hideEndSession} onChange={setHideEndSession} size="small" />
        <span
          style={{ fontSize: 13 }}
          title="隐藏 Sample.end_session=true 的批次(仅释放设备,不是真实对话轮次)"
        >
          隐藏结束会话记录
        </span>
      </Space>
      <Space size={6}>
        <Switch checked={durationAnomalyOnly} onChange={setDurationAnomalyOnly} size="small" />
        <span
          style={{ fontSize: 13 }}
          title="只看单样本批次中,耗时明显偏离该 profile 历史平均耗时(>2倍或<0.5倍)的批次"
        >
          只看耗时异常
        </span>
      </Space>
    </Space>
  )

  return (
    <div>
      <BatchPromptModal
        batchId={previewBatchId}
        onClose={() => setPreviewBatchId(null)}
      />
      <SessionConversationModal
        sessionId={conversationSessionId}
        onClose={() => setConversationSessionId(null)}
      />
      <DeviceStreamModal serial={streamSerial} onClose={() => setStreamSerial(null)} />
      <PageHeader
        eyebrow="任务"
        title="批次 Batches"
        subtitle={
          total > 0
            ? `共 ${total} 个批次${debouncedQ ? `,匹配 "${debouncedQ}"` : ''}`
            : undefined
        }
        extra={
          <Space>
            <Dropdown
              menu={{
                items: [
                  {
                    key: 'failed',
                    label: `删除全部 failed (${stats?.failed ?? 0})`,
                    disabled: (stats?.failed ?? 0) === 0,
                  },
                  {
                    key: 'cancelled',
                    label: `删除全部 cancelled (${stats?.cancelled ?? 0})`,
                    disabled: (stats?.cancelled ?? 0) === 0,
                  },
                  {
                    key: 'done',
                    label: `删除全部 done (${stats?.done ?? 0})`,
                    disabled: (stats?.done ?? 0) === 0,
                  },
                  { type: 'divider' as const },
                  {
                    key: 'terminal',
                    label: `删除全部已完成（done/failed/cancelled）`,
                  },
                ],
                onClick: ({ key }) =>
                  onBulkDelete(key as 'done' | 'failed' | 'cancelled' | 'terminal'),
              }}
              disabled={deleteByStatus.isPending}
            >
              <Button
                danger
                icon={<DeleteOutlined />}
                loading={deleteByStatus.isPending}
              >
                批量删除
              </Button>
            </Dropdown>
            <Popconfirm
              title="取消所有进行中批次"
              description={
                activeCount > 0
                  ? `当前有 ${activeCount} 个 queued/running 批次，全部停掉？`
                  : '当前没有进行中的批次（仅清理可能的孤儿状态）。'
              }
              onConfirm={onCancelActive}
              okText="取消全部"
              cancelText="不"
              disabled={cancelActive.isPending}
            >
              <Button
                danger
                icon={<StopOutlined />}
                loading={cancelActive.isPending}
                disabled={activeCount === 0 && !cancelActive.isPending}
              >
                取消全部 {activeCount > 0 ? `(${activeCount})` : ''}
              </Button>
            </Popconfirm>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/batches/new')}>
              新建批次
            </Button>
          </Space>
        }
      />
      <Space wrap style={{ marginBottom: activeFilters.length ? 8 : 14 }}>
        <Input.Search
          placeholder="搜索批次名 / ID / Prompt 内容"
          allowClear
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          style={{ width: 340 }}
        />
        <Popover content={filterPopover} trigger="click" placement="bottomLeft">
          <Badge count={activeFilters.length} size="small">
            <Button icon={<FilterOutlined />}>筛选</Button>
          </Badge>
        </Popover>
        <Popover
          trigger="click"
          placement="bottomLeft"
          content={
            <Space direction="vertical" size={6}>
              {TOGGLEABLE_COLUMNS.map((c) => (
                <Checkbox
                  key={c.key}
                  checked={visibleCols.has(c.key)}
                  onChange={() => toggleCol(c.key)}
                >
                  {c.label}
                </Checkbox>
              ))}
            </Space>
          }
        >
          <Button icon={<SettingOutlined />}>列</Button>
        </Popover>
      </Space>
      {activeFilters.length > 0 ? (
        <Space wrap size={6} style={{ marginBottom: 14 }}>
          {activeFilters.map((f) => (
            <Tag key={f.key} closable onClose={f.onClear} style={{ marginInlineEnd: 0 }}>
              {f.label}
            </Tag>
          ))}
          <a style={{ fontSize: 12 }} onClick={clearAllFilters}>
            清除全部
          </a>
        </Space>
      ) : null}
      {isError ? (
        <ErrorState
          description="无法读取批次列表"
          detail={error instanceof Error ? error.message : undefined}
          onRetry={() => refetch()}
        />
      ) : rows.length === 0 && !isLoading ? (
        <EmptyState
          icon={<ExperimentOutlined />}
          title={debouncedQ || activeFilters.length > 0 ? '没有匹配的批次' : '还没有批次'}
          description={
            debouncedQ || activeFilters.length > 0
              ? '换个关键字或筛选条件,或清空筛选看全部。'
              : '创建第一个批次开始批量测试。'
          }
          action={
            <Button type="primary" onClick={() => navigate('/batches/new')}>
              新建批次
            </Button>
          }
        />
      ) : (
        <>
          {selectedIds.length > 0 ? (
            <Space style={{ marginBottom: 10 }}>
              <span style={{ fontSize: 13 }}>已选 {selectedIds.length} 项</span>
              <Popconfirm
                title={`取消选中的 ${selectedIds.length} 个批次?`}
                description="仅对 queued/running 的批次生效。"
                onConfirm={() => runBulk('取消', (id) => cancelOne.mutateAsync(id))}
                okText="取消批次"
                cancelText="返回"
              >
                <Button size="small" icon={<StopOutlined />} loading={bulkBusy}>
                  批量取消
                </Button>
              </Popconfirm>
              <Popconfirm
                title={`删除选中的 ${selectedIds.length} 个批次?`}
                description="连同 DB 记录 / JSONL / logs 一并删除,不可恢复。active 批次会删除失败。"
                onConfirm={() => runBulk('删除', (id) => deleteOne.mutateAsync(id))}
                okText="删除"
                okButtonProps={{ danger: true }}
                cancelText="返回"
              >
                <Button size="small" danger icon={<DeleteOutlined />} loading={bulkBusy}>
                  批量删除
                </Button>
              </Popconfirm>
              <a style={{ fontSize: 12 }} onClick={() => setSelectedIds([])}>
                清除选择
              </a>
            </Space>
          ) : null}
          <Table<BatchSummary>
            rowKey="batch_id"
            size="small"
            loading={isLoading}
            dataSource={rows}
            columns={resizableColumns}
            components={resizableComponents}
            rowSelection={{
              selectedRowKeys: selectedIds,
              onChange: (keys) => setSelectedIds(keys as string[]),
              preserveSelectedRowKeys: true,
            }}
            pagination={{
              current: page,
              pageSize,
              total,
              showSizeChanger: true,
              pageSizeOptions: ['20', '50', '100', '200'],
              showTotal: (n) => `共 ${n} 条`,
              onChange: setPagination,
            }}
          />
        </>
      )}
    </div>
  )
}
