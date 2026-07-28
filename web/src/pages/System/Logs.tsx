import {
  DownloadOutlined,
  ReloadOutlined,
  VerticalAlignBottomOutlined,
} from '@ant-design/icons'
import { Button, Input, Select, Skeleton, Space, Switch, Typography } from 'antd'
import type * as monacoNS from 'monaco-editor'
import { Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react'

import { downloadAppLog, useAppLog } from '../../api/system'
import { EmptyState } from '../../components/states/EmptyState'
import { ErrorState } from '../../components/states/ErrorState'
import { PageHeader } from '../../components/states/PageHeader'
import { LOG_LEVELS, type LogLevel, filterLogContent } from '../../utils/logFilter'

// Lazy — LogViewer pulls in Monaco (same ~4MB chunk YamlEditor uses), and
// this page shouldn't make every other page pay for it on initial load.
const LogViewer = lazy(() =>
  import('../../components/LogViewer').then((m) => ({ default: m.LogViewer })),
)

const LINE_OPTIONS = [200, 500, 1000, 2000, 5000]
const AUTO_REFRESH_MS = 5000

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function LogsPage() {
  const [lines, setLines] = useState(1000)
  const [autoRefresh, setAutoRefresh] = useState(false)
  const [levels, setLevels] = useState<LogLevel[]>([...LOG_LEVELS])
  const [search, setSearch] = useState('')
  const editorRef = useRef<monacoNS.editor.IStandaloneCodeEditor | null>(null)

  const { data, isLoading, isError, error, refetch, isFetching } = useAppLog(
    lines,
    autoRefresh ? AUTO_REFRESH_MS : false,
  )

  const filteredContent = useMemo(
    () => filterLogContent(data?.content ?? '', { levels: new Set(levels), search }),
    [data?.content, levels, search],
  )
  const isFiltered = levels.length < LOG_LEVELS.length || search.trim() !== ''
  const totalLineCount = data?.content ? data.content.split('\n').length : 0
  const filteredLineCount = filteredContent ? filteredContent.split('\n').length : 0

  const scrollToBottom = () => {
    const editor = editorRef.current
    const model = editor?.getModel()
    if (!editor || !model) return
    editor.revealLine(model.getLineCount())
  }

  // Re-tail (initial load, manual refresh, or an auto-refresh tick) always
  // jumps to the newest content — matches `tail -f` expectations. Pause
  // 自动刷新 to read older output without being pulled back down.
  useEffect(() => {
    scrollToBottom()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filteredContent])

  return (
    <div>
      <PageHeader
        eyebrow="系统"
        title="运行日志 Logs"
        subtitle={
          data?.exists
            ? `${data.path} · ${formatSize(data.size_bytes)}${
                data.truncated ? ' · 仅显示末尾部分' : ''
              }`
            : '应用进程的 stdout/stderr 运行日志(由 run.sh 写入)'
        }
        extra={
          <Space wrap>
            <Select
              value={lines}
              onChange={setLines}
              options={LINE_OPTIONS.map((n) => ({ value: n, label: `最近 ${n} 行` }))}
              style={{ width: 120 }}
            />
            <Select
              mode="multiple"
              value={levels}
              onChange={setLevels}
              options={LOG_LEVELS.map((l) => ({ value: l, label: l }))}
              maxTagCount="responsive"
              placeholder="日志级别"
              style={{ width: 220 }}
            />
            <Input.Search
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索日志内容"
              allowClear
              style={{ width: 220 }}
            />
            <Space size={6}>
              <Switch checked={autoRefresh} onChange={setAutoRefresh} size="small" />
              <Typography.Text style={{ fontSize: 13 }}>自动刷新</Typography.Text>
            </Space>
            <Button icon={<ReloadOutlined />} loading={isFetching} onClick={() => refetch()}>
              刷新
            </Button>
            <Button icon={<VerticalAlignBottomOutlined />} onClick={scrollToBottom}>
              跳到底部
            </Button>
            <Button icon={<DownloadOutlined />} onClick={() => downloadAppLog()}>
              下载完整日志
            </Button>
          </Space>
        }
      />
      {isFiltered && data?.exists ? (
        <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
          筛选后显示 {filteredLineCount} / {totalLineCount} 行
        </Typography.Text>
      ) : null}
      {isError ? (
        <ErrorState
          title="日志加载失败"
          description="可能是网络问题或后端暂时不可用。"
          detail={(error as Error)?.message}
          onRetry={() => refetch()}
        />
      ) : !isLoading && data && !data.exists ? (
        <EmptyState
          title="尚未找到日志文件"
          description={`预期路径:${data.path}。通过 run.sh 启动服务后才会写入该文件;开发模式下直接用 uvicorn 启动不会产生此文件。`}
          action={
            <Button icon={<ReloadOutlined />} onClick={() => refetch()}>
              重新检查
            </Button>
          }
        />
      ) : (
        <Suspense fallback={<Skeleton active paragraph={{ rows: 10 }} />}>
          <LogViewer
            value={filteredContent}
            height="calc(100vh - 260px)"
            onMount={(editor) => {
              editorRef.current = editor
              scrollToBottom()
            }}
          />
        </Suspense>
      )}
    </div>
  )
}
