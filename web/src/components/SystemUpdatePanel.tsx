import { CheckCircleTwoTone, CloseCircleTwoTone } from '@ant-design/icons'
import { App, Alert, Button, Card, Space, Tag, Typography } from 'antd'
import { useState } from 'react'
import {
  ApplyResult,
  PreflightResult,
  probeHealth,
  useApplyUpdate,
  useCheckUpdate,
  usePreflight,
  useUpdateStatus,
} from '../api/system'

const { Text, Paragraph } = Typography

interface ActiveBatchDetail {
  error?: string
  active_batches?: number
}

function activeBatchCount(err: unknown): number | null {
  const detail = (err as { response?: { data?: { detail?: ActiveBatchDetail } } })?.response?.data
    ?.detail
  if (detail?.error === 'active_batches') return detail.active_batches ?? 0
  // ApiError (normalizeError) shape: { data?: { detail?: ... } }
  const alt = (err as { data?: { detail?: ActiveBatchDetail } })?.data?.detail
  if (alt?.error === 'active_batches') return alt.active_batches ?? 0
  return null
}

/** Polls /health until it comes back on a commit different from `before`. */
async function waitForRestart(before: string | null, onTick: (n: number) => void): Promise<void> {
  for (let i = 0; i < 60; i++) {
    onTick(i)
    await new Promise((r) => setTimeout(r, 2000))
    const h = await probeHealth()
    if (h && h.status === 'ok' && h.commit !== before) return
  }
}

export function SystemUpdatePanel() {
  const { modal, message } = App.useApp()
  const status = useUpdateStatus()
  const check = useCheckUpdate()
  const apply = useApplyUpdate()
  const preflight = usePreflight()
  const [steps, setSteps] = useState<string[]>([])
  const [restarting, setRestarting] = useState(false)
  const [pf, setPf] = useState<PreflightResult | null>(null)

  const s = status.data
  // Fail closed: if status couldn't be loaded at all, we don't actually
  // know whether self-update is enabled or what state the app is in — this
  // used to default to `false` (buttons enabled), silently offering apply
  // and letting the version tag just show "未知" as if that were normal.
  const disabled = s ? !s.enabled : true

  const runApply = async (force: boolean) => {
    setSteps([])
    let result: ApplyResult
    try {
      result = await apply.mutateAsync(force)
    } catch (err) {
      const n = activeBatchCount(err)
      if (n !== null) {
        modal.confirm({
          title: '有任务正在运行',
          content: `当前有 ${n} 个批次在运行,重启会中断它们。确认继续更新?`,
          okText: '强制更新并重启',
          okButtonProps: { danger: true },
          cancelText: '取消',
          onOk: () => runApply(true),
        })
        return
      }
      const detail = (err as { data?: { detail?: { steps?: string[]; error?: string } } })?.data
        ?.detail
      if (detail?.steps) setSteps(detail.steps)
      message.error(detail?.error ?? (err as Error).message ?? '更新失败')
      return
    }
    setSteps(result.steps)
    if (result.restarting) {
      setRestarting(true)
      message.info('已拉取新代码,正在重启服务…')
      await waitForRestart(s?.current_short ?? null, () => {})
      message.success('服务已在新版本上重启,即将刷新页面')
      setTimeout(() => window.location.reload(), 800)
    } else {
      message.success('已是最新,无需重启')
    }
  }

  return (
    <Card title="系统更新" size="small">
      <Alert
        style={{ marginBottom: 12 }}
        type="warning"
        showIcon
        message="从 origin/main 拉取最新代码并原地重启。这等同于远程代码执行,请仅在信任来源时启用。"
      />

      {status.isError ? (
        <Alert
          style={{ marginBottom: 12 }}
          type="error"
          showIcon
          message="状态加载失败,版本/更新信息不可靠"
          description={(status.error as Error)?.message}
          action={
            <Button size="small" onClick={() => status.refetch()}>
              重试
            </Button>
          }
        />
      ) : disabled ? (
        <Alert
          style={{ marginBottom: 12 }}
          type="info"
          showIcon
          message="自更新当前未启用。请到「运行默认」中打开「启用自更新」后再使用。"
        />
      ) : null}

      <Space direction="vertical" size={10} style={{ width: '100%' }}>
        <Space wrap size={8}>
          <Text type="secondary">当前版本</Text>
          <Tag className="aa-mono">{s?.current_short ?? '未知'}</Tag>
          {s && !s.up_to_date ? (
            <>
              <Text type="secondary">→ 远端</Text>
              <Tag color="blue" className="aa-mono">
                {s.remote_short}
              </Tag>
              <Tag color="orange">落后 {s.behind} 个提交</Tag>
            </>
          ) : (
            <Tag color="green">已是最新</Tag>
          )}
        </Space>

        <Space wrap size={8}>
          <Button
            onClick={async () => {
              try {
                setPf(await preflight.mutateAsync())
              } catch (e) {
                message.error((e as Error).message)
              }
            }}
            loading={preflight.isPending}
          >
            环境自检
          </Button>
          <Button
            onClick={async () => {
              try {
                await check.mutateAsync()
                await status.refetch()
                message.success('已检查更新')
              } catch (e) {
                message.error((e as Error).message)
              }
            }}
            loading={check.isPending}
            disabled={disabled}
          >
            检查更新
          </Button>
          <Button
            type="primary"
            danger
            disabled={disabled || !!s?.up_to_date || restarting}
            loading={apply.isPending || restarting}
            onClick={() => void runApply(false)}
          >
            {restarting ? '正在重启…' : '应用并重启'}
          </Button>
        </Space>

        {pf ? <PreflightChecklist pf={pf} /> : null}

        {s?.error ? <Alert type="error" showIcon message={s.error} /> : null}

        {s && !s.up_to_date && s.changelog.length > 0 ? (
          <Card size="small" type="inner" title="待应用的提交">
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {s.changelog.map((line, i) => (
                <Text key={i} className="aa-mono" style={{ fontSize: 12 }}>
                  {line}
                </Text>
              ))}
            </div>
          </Card>
        ) : null}

        {steps.length > 0 ? (
          <Card size="small" type="inner" title="执行日志">
            <Paragraph>
              <pre
                style={{
                  margin: 0,
                  maxHeight: 260,
                  overflow: 'auto',
                  fontSize: 12,
                  whiteSpace: 'pre-wrap',
                }}
              >
                {steps.join('\n')}
              </pre>
            </Paragraph>
          </Card>
        ) : null}
      </Space>
    </Card>
  )
}

function CheckRow({ ok, label, detail }: { ok: boolean; label: string; detail: string }) {
  return (
    <Space size={8} align="start">
      {ok ? (
        <CheckCircleTwoTone twoToneColor="#52c41a" />
      ) : (
        <CloseCircleTwoTone twoToneColor="#ff4d4f" />
      )}
      <Text style={{ minWidth: 96, display: 'inline-block' }}>{label}</Text>
      <Text type="secondary" className="aa-mono" style={{ fontSize: 12 }}>
        {detail}
      </Text>
    </Space>
  )
}

function PreflightChecklist({ pf }: { pf: PreflightResult }) {
  return (
    <Card
      size="small"
      type="inner"
      title="环境自检"
      extra={
        pf.ok ? (
          <Tag color="green">就绪</Tag>
        ) : (
          <Tag color="red">存在问题,更新会中止</Tag>
        )
      }
    >
      <Space direction="vertical" size={6} style={{ width: '100%' }}>
        {pf.tools.map((t) => (
          <CheckRow key={t.name} ok={t.ok} label={t.name} detail={t.detail} />
        ))}
        <CheckRow ok={pf.remote_ok} label="远端可拉取" detail={pf.remote_detail} />
        <CheckRow ok={pf.tree_clean} label="工作区干净" detail={pf.tree_detail} />
      </Space>
    </Card>
  )
}
