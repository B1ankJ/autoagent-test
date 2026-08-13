import { DeleteOutlined, DownloadOutlined } from '@ant-design/icons'
import {
  Alert,
  App,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Popconfirm,
  Space,
  Switch,
  Tabs,
  Typography,
} from 'antd'
import type { ReactNode } from 'react'
import { useEffect, useState } from 'react'
import {
  DingTalkConfig,
  LLMCheckResult,
  downloadBackup,
  useAddBlacklist,
  useAddWhitelist,
  useBackupList,
  useBlacklist,
  useDefaults,
  useDeleteBackup,
  useNotifications,
  usePreviewLogsCleanup,
  useRemoveBlacklist,
  useRemoveWhitelist,
  useRunBackup,
  useRunLogsCleanup,
  useSaveDefaults,
  useSaveNotifications,
  useSaveVLM,
  useTestLLM,
  useTestNotifications,
  useVLM,
  useWhitelist,
} from '../api/config'
import { useBackfillAnomalies } from '../api/anomalies'
import { PageHeader } from '../components/states/PageHeader'
import { ResponseListPanel } from '../components/ResponseListPanel'
import { SystemUpdatePanel } from '../components/SystemUpdatePanel'
import { GlobalDefaults, VLMConfig } from '../types/api'
import { ApiError } from '../utils/errors'

const STAGE_TEXT: Record<LLMCheckResult['stage'], string> = {
  connect: '无法连接到该地址',
  auth: '认证失败',
  model_not_found: '模型不存在',
  response_shape: '返回格式异常',
  ok: '连通正常',
}

function humanBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`
}

/** Visually groups a set of related Form.Items (e.g. one DingTalk rule's
 * fields) inside a bordered box, so a long flat form reads as sections
 * instead of an undifferentiated list of fields. */
function RuleSection({
  title,
  description,
  children,
}: {
  title: string
  description?: string
  children: ReactNode
}) {
  return (
    <div
      style={{
        background: '#fafafa',
        border: '1px solid #f0f0f0',
        borderRadius: 8,
        padding: '12px 16px 0',
        marginBottom: 20,
      }}
    >
      <Typography.Text strong style={{ display: 'block', marginBottom: description ? 2 : 8 }}>
        {title}
      </Typography.Text>
      {description ? (
        <Typography.Text
          type="secondary"
          style={{ display: 'block', fontSize: 12, marginBottom: 8 }}
        >
          {description}
        </Typography.Text>
      ) : null}
      {children}
    </div>
  )
}

function saveErrorMessage(error: unknown): string {
  // The api/client.ts interceptor already normalizes any error into an
  // ApiError before it reaches a mutation's catch block — there's no
  // `.response` on it to read `.detail` off of the way a raw axios error
  // would have. PUT /config/vlm's 400 body is a JSON-serialized
  // LLMCheckResult (stage/message), which normalizeError stringifies into
  // ApiError.detail — parse it back out for the friendlier Chinese message.
  if (error instanceof ApiError) {
    try {
      const parsed = JSON.parse(error.detail) as Partial<LLMCheckResult>
      if (parsed && typeof parsed === 'object' && parsed.stage) {
        return `${STAGE_TEXT[parsed.stage] ?? '未知错误'}：${parsed.message ?? ''}`
      }
    } catch {
      // detail wasn't JSON — it's already a plain message string, fall through.
    }
    return error.message
  }
  return (error as Error).message ?? '未知错误'
}

export function ConfigPage() {
  const vlm = useVLM()
  const defaults = useDefaults()
  const saveVlm = useSaveVLM()
  const testLlm = useTestLLM()
  const saveDefaults = useSaveDefaults()
  const notifications = useNotifications()
  const saveNotifications = useSaveNotifications()
  const backfillAnomalies = useBackfillAnomalies()
  const testNotifications = useTestNotifications()
  const whitelist = useWhitelist()
  const addWhitelist = useAddWhitelist()
  const removeWhitelist = useRemoveWhitelist()
  const blacklist = useBlacklist()
  const addBlacklist = useAddBlacklist()
  const removeBlacklist = useRemoveBlacklist()
  const previewLogsCleanup = usePreviewLogsCleanup()
  const runLogsCleanup = useRunLogsCleanup()
  const backupList = useBackupList()
  const runBackup = useRunBackup()
  const deleteBackup = useDeleteBackup()
  const [vlmForm] = Form.useForm<VLMConfig>()
  const [defaultsForm] = Form.useForm<GlobalDefaults>()
  const [notifyForm] = Form.useForm<DingTalkConfig>()
  const [notifyTestMsg, setNotifyTestMsg] = useState<string | null>(null)
  const [notifyTestOk, setNotifyTestOk] = useState(false)
  const { message } = App.useApp()
  const [llmTestMessage, setLlmTestMessage] = useState<string | null>(null)
  const [llmTestOk, setLlmTestOk] = useState(false)

  useEffect(() => {
    if (vlm.data) {
      vlmForm.setFieldsValue(vlm.data)
    }
  }, [vlm.data, vlmForm])

  useEffect(() => {
    if (defaults.data) {
      defaultsForm.setFieldsValue(defaults.data)
    }
  }, [defaults.data, defaultsForm])

  useEffect(() => {
    if (notifications.data) {
      notifyForm.setFieldsValue(notifications.data)
    }
  }, [notifications.data, notifyForm])

  const handleTestNotify = async () => {
    const values = notifyForm.getFieldsValue()
    if (!values.webhook_url?.trim()) {
      setNotifyTestOk(false)
      setNotifyTestMsg('请先填写 Webhook URL')
      return
    }
    try {
      const result = await testNotifications.mutateAsync(values)
      setNotifyTestOk(result.ok)
      setNotifyTestMsg(
        result.ok
          ? '✅ 测试消息已发送,请检查群里是否收到'
          : `❌ 发送失败: ${result.errmsg ?? 'unknown'} (status=${result.status_code ?? '-'}, errcode=${result.errcode ?? '-'})`,
      )
    } catch (e) {
      setNotifyTestOk(false)
      setNotifyTestMsg((e as Error).message)
    }
  }

  const handleTestLLM = async () => {
    const values = vlmForm.getFieldsValue()
    if (!values.base_url || !values.model || !values.api_key) {
      setLlmTestOk(false)
      setLlmTestMessage('请先填写完整的 Base URL、Model 和 API Key')
      return
    }
    try {
      const result = await testLlm.mutateAsync({
        base_url: values.base_url,
        model: values.model,
        api_key: values.api_key,
      })
      setLlmTestOk(result.ok)
      setLlmTestMessage(
        result.ok
          ? `${STAGE_TEXT[result.stage]}（${result.latency_ms} ms）`
          : `${STAGE_TEXT[result.stage]}：${result.message}`,
      )
    } catch (e) {
      setLlmTestOk(false)
      setLlmTestMessage((e as Error).message)
    }
  }

  return (
    <div>
      <PageHeader eyebrow="系统" title="设置 Config" subtitle="VLM 凭据与运行时全局默认值" />
      <Tabs
        style={{ maxWidth: 760 }}
        items={[
          {
            key: 'vlm',
            label: 'VLM',
            children: (
              <Card title="VLM" size="small">
                {vlm.isError ? (
                  <Alert
                    style={{ marginBottom: 12 }}
                    type="error"
                    showIcon
                    message="配置加载失败"
                    description={(vlm.error as Error)?.message}
                    action={
                      <Button size="small" onClick={() => vlm.refetch()}>
                        重试
                      </Button>
                    }
                  />
                ) : null}
                <Form
                  form={vlmForm}
                  layout="vertical"
                  onFinish={async (values) => {
                    try {
                      await saveVlm.mutateAsync(values)
                      message.success('已保存')
                    } catch (error) {
                      message.error(saveErrorMessage(error))
                    }
                  }}
                >
                  <Form.Item name="base_url" label="Base URL" rules={[{ required: true }]}>
                    <Input />
                  </Form.Item>
                  <Form.Item name="model" label="Model" rules={[{ required: true }]}>
                    <Input />
                  </Form.Item>
                  <Form.Item name="api_key" label="API Key">
                    <Input.Password />
                  </Form.Item>
                  <Space>
                    <Button type="primary" htmlType="submit" loading={saveVlm.isPending}>
                      保存
                    </Button>
                    <Button onClick={() => void handleTestLLM()} loading={testLlm.isPending}>
                      测试连通性
                    </Button>
                  </Space>
                  {llmTestMessage ? (
                    <Alert
                      style={{ marginTop: 12 }}
                      type={llmTestOk ? 'success' : 'error'}
                      showIcon
                      message={llmTestMessage}
                    />
                  ) : null}
                </Form>
              </Card>
            ),
          },
          {
            key: 'defaults',
            label: '运行默认',
            children: (
              <Card title="Global Defaults" size="small">
                {defaults.isError ? (
                  <Alert
                    style={{ marginBottom: 12 }}
                    type="error"
                    showIcon
                    message="配置加载失败"
                    description={(defaults.error as Error)?.message}
                    action={
                      <Button size="small" onClick={() => defaults.refetch()}>
                        重试
                      </Button>
                    }
                  />
                ) : null}
                <Form
                  form={defaultsForm}
                  layout="vertical"
                  onFinish={async (values) => {
                    try {
                      await saveDefaults.mutateAsync(values)
                      message.success('已保存')
                    } catch (error) {
                      message.error((error as Error).message)
                    }
                  }}
                >
                  <Form.Item name="api_timeout_sec" label="API timeout (s)">
                    <InputNumber min={1} />
                  </Form.Item>
                  <Form.Item name="gui_timeout_sec" label="GUI timeout (s)">
                    <InputNumber min={1} />
                  </Form.Item>
                  <Form.Item name="retry" label="Retry">
                    <InputNumber min={0} max={10} />
                  </Form.Item>
                  <Form.Item name="concurrency" label="Concurrency">
                    <InputNumber min={1} max={10} />
                  </Form.Item>
                  <Form.Item name="verbose_logs" label="Verbose logs" valuePropName="checked">
                    <Switch />
                  </Form.Item>
                  <Form.Item
                    name="log_retention_days"
                    label="数据保留天数"
                    extra="0 = 关闭自动清理。启用后每日一次:删除超过该天数的已完成批次(DB 记录 + 结果 JSONL + 日志),并清理 logs/ 与 data/profile_builder/ 下的过期产物。"
                  >
                    <InputNumber min={0} max={365} />
                  </Form.Item>
                  <Form.Item
                    name="archive_retention_days"
                    label="归档保留天数"
                    extra="0 = 不归档,批次直接删除。> 0:批次被清理前,先把结果 JSONL + 日志 + DB 快照打包到 data/archive/<batch>.zip;归档包本身在该天数后才删除(建议 ≥ 数据保留天数)。归档失败时会跳过删除以防丢数据。"
                  >
                    <InputNumber min={0} max={365} />
                  </Form.Item>
                  <Form.Item
                    name="backup_retention_days"
                    label="备份保留天数"
                    extra="0 = 关闭自动备份。> 0:定期(见下方间隔)把 SQLite 数据库(在线备份,WAL 安全)+ profiles/*.yaml 打包到 data/backups/<时间戳>.zip,备份包本身保留该天数。不含 results/logs——它们已有独立的保留/归档策略。"
                  >
                    <InputNumber min={0} max={365} />
                  </Form.Item>
                  <Form.Item
                    name="backup_interval_hours"
                    label="备份间隔(小时)"
                    extra="自动备份任务的运行间隔,仅在备份保留天数 > 0 时生效。"
                  >
                    <InputNumber min={1} max={168} />
                  </Form.Item>
                  <Form.Item
                    name="backup_max_count"
                    label="最多保留备份数"
                    extra="0 = 不限数量,仅按保留天数清理。> 0:只保留最新的这么多个备份,多余的自动删除(与保留天数同时生效,谁删得多算谁)。默认 3。"
                  >
                    <InputNumber min={0} max={100} />
                  </Form.Item>
                  <Form.Item
                    name="self_update_enabled"
                    label="启用自更新"
                    valuePropName="checked"
                    extra="打开后可在「系统更新」页从 origin/main 拉取新代码并原地重启。等同远程代码执行,仅在信任来源时开启。"
                  >
                    <Switch />
                  </Form.Item>
                  <Form.Item
                    name="device_autoheal_enabled"
                    label="设备自动重连"
                    valuePropName="checked"
                    extra="开启后,离线的网络(wifi)设备会在设备监控轮询里自动 adb connect 重连(指数退避)。只对网络设备生效,跳过 USB/已禁用/初始化中/占用中的设备,不 reboot。默认关。"
                  >
                    <Switch />
                  </Form.Item>
                  <Space>
                    <Button type="primary" htmlType="submit" loading={saveDefaults.isPending}>
                      保存
                    </Button>
                    <Button
                      onClick={async () => {
                        try {
                          const days = defaultsForm.getFieldValue('log_retention_days') as number
                          const r = await previewLogsCleanup.mutateAsync(days || undefined)
                          const archived = r.batches_archived
                            ? `(其中 ${r.batches_archived} 个先归档)`
                            : ''
                          message.info(
                            `预览:将清理 ${r.batches_pruned} 个过期批次${archived}、${r.files_deleted} 个文件 / ${r.dirs_deleted} 个目录,释放 ${humanBytes(r.bytes_freed)}`,
                          )
                        } catch (e) {
                          message.error((e as Error).message)
                        }
                      }}
                      loading={previewLogsCleanup.isPending}
                    >
                      预览清理
                    </Button>
                    <Popconfirm
                      title="立即清理"
                      description="根据当前保留天数删除过期批次(含 DB 记录/结果)与日志/Builder 产物。不可恢复。"
                      onConfirm={async () => {
                        try {
                          const days = defaultsForm.getFieldValue('log_retention_days') as number
                          const r = await runLogsCleanup.mutateAsync(days || undefined)
                          const archived = r.batches_archived
                            ? `(其中 ${r.batches_archived} 个已归档)`
                            : ''
                          message.success(
                            `已清理 ${r.batches_pruned} 个过期批次${archived}、${r.files_deleted} 个文件 / ${r.dirs_deleted} 个目录,释放 ${humanBytes(r.bytes_freed)}`,
                          )
                        } catch (e) {
                          message.error((e as Error).message)
                        }
                      }}
                      okText="删除"
                      okButtonProps={{ danger: true }}
                      cancelText="取消"
                    >
                      <Button danger loading={runLogsCleanup.isPending}>
                        立即清理
                      </Button>
                    </Popconfirm>
                    <Button
                      onClick={async () => {
                        try {
                          const r = await runBackup.mutateAsync()
                          message.success(
                            r.path
                              ? `已备份到 ${r.path.split('/').pop()}(${humanBytes(r.bytes_written)}），清理过期备份 ${r.pruned} 个`
                              : '未找到数据库文件,跳过备份',
                          )
                        } catch (e) {
                          message.error((e as Error).message)
                        }
                      }}
                      loading={runBackup.isPending}
                    >
                      立即备份
                    </Button>
                  </Space>
                  {backupList.data && backupList.data.length > 0 ? (
                    <div style={{ marginTop: 12 }}>
                      <Typography.Text
                        type="secondary"
                        style={{ fontSize: 12, display: 'block', marginBottom: 6 }}
                      >
                        已有备份({backupList.data.length})
                      </Typography.Text>
                      <div
                        style={{
                          display: 'flex',
                          flexDirection: 'column',
                          gap: 4,
                          maxHeight: 220,
                          overflowY: 'auto',
                        }}
                      >
                        {backupList.data.map((b) => (
                          <div
                            key={b.name}
                            style={{
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'space-between',
                              fontSize: 12,
                              padding: '4px 4px 4px 8px',
                              border: '1px solid var(--aa-border, #eee)',
                              borderRadius: 4,
                            }}
                          >
                            <span className="aa-mono">{b.name}</span>
                            <Space size={4}>
                              <span className="aa-muted">{humanBytes(b.bytes)}</span>
                              <Button
                                type="text"
                                size="small"
                                icon={<DownloadOutlined />}
                                title="下载该备份"
                                aria-label="下载该备份"
                                onClick={() => void downloadBackup(b.name)}
                              />
                              <Popconfirm
                                title="删除该备份"
                                description="删除后不可恢复。"
                                okText="删除"
                                okButtonProps={{ danger: true }}
                                cancelText="取消"
                                onConfirm={async () => {
                                  try {
                                    await deleteBackup.mutateAsync(b.name)
                                    message.success('已删除')
                                  } catch (e) {
                                    message.error((e as Error).message)
                                  }
                                }}
                              >
                                <Button
                                  type="text"
                                  size="small"
                                  danger
                                  icon={<DeleteOutlined />}
                                  title="删除该备份"
                                  aria-label="删除该备份"
                                  loading={deleteBackup.isPending}
                                />
                              </Popconfirm>
                            </Space>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </Form>
              </Card>
            ),
          },
          {
            key: 'notify',
            label: '钉钉通知',
            children: (
              <Card title="钉钉通知" size="small">
                {notifications.isError ? (
                  <Alert
                    style={{ marginBottom: 12 }}
                    type="error"
                    showIcon
                    message="配置加载失败"
                    description={(notifications.error as Error)?.message}
                    action={
                      <Button size="small" onClick={() => notifications.refetch()}>
                        重试
                      </Button>
                    }
                  />
                ) : null}
                <Form
                  form={notifyForm}
                  layout="vertical"
                  onFinish={async (values) => {
                    try {
                      await saveNotifications.mutateAsync(values)
                      message.success('已保存')
                    } catch (error) {
                      message.error((error as Error).message)
                    }
                  }}
                >
                  <Typography.Title level={5} style={{ marginTop: 0 }}>
                    基础设置
                  </Typography.Title>
                  <Form.Item name="enabled" label="启用通知" valuePropName="checked">
                    <Switch />
                  </Form.Item>
                  <Form.Item
                    name="webhook_url"
                    label="Webhook URL"
                    extra="钉钉自定义机器人的 webhook 地址"
                  >
                    <Input placeholder="https://oapi.dingtalk.com/robot/send?access_token=..." />
                  </Form.Item>
                  <Form.Item
                    name="secret"
                    label="Secret(可选,加签模式)"
                    extra="如果机器人安全设置选了「加签」,填这里;否则留空"
                  >
                    <Input.Password placeholder="SEC..." />
                  </Form.Item>
                  <Form.Item
                    name="app_base_url"
                    label="AutoAgent 访问地址(可选)"
                    extra="填了以后,告警消息里的 sample 引用会变成可点击链接,直接跳到该 sample 详情页(含截图)。钉钉自定义机器人不支持带鉴权的图片直传,所以走链接而不是内嵌图。留空则仍显示为纯文本。"
                  >
                    <Input placeholder="https://autoagent.example.com" />
                  </Form.Item>
                  <Form.Item name="at_all" label="@ 全体" valuePropName="checked">
                    <Switch />
                  </Form.Item>

                  <RuleSection
                    title="规则 1 · 连续空响应"
                    description="同一设备连续 N 次有效响应为空(已按 LLM 复核结果判断,status=done)时触发提醒。"
                  >
                    <Form.Item name="empty_response_threshold" label="连续空响应阈值">
                      <InputNumber min={1} max={20} />
                    </Form.Item>
                    <Form.Item
                      name="empty_response_auto_reinit"
                      label="连续空响应时自动重新初始化设备"
                      valuePropName="checked"
                      extra="触发通知时自动运行该 profile 的初始化剧本复位设备(等当前任务结束后执行)。需 profile 配好 init_action。与规则 2 的自动复位开关相互独立。"
                    >
                      <Switch />
                    </Form.Item>
                  </RuleSection>

                  <RuleSection
                    title="规则 2 · 连续相同响应"
                    description="同设备连续 N 次响应一样 → 截图交给 VLM 判断是否还停留在聊天页;白名单按 profile 维度(需 VLM 已配置)。"
                  >
                    <Form.Item
                      name="same_response_enabled"
                      label="启用重复响应检测"
                      valuePropName="checked"
                    >
                      <Switch />
                    </Form.Item>
                    <Form.Item name="same_response_threshold" label="连续相同响应阈值">
                      <InputNumber min={1} max={20} />
                    </Form.Item>
                    <Form.Item
                      name="same_response_auto_reinit"
                      label="异常时自动重新初始化设备"
                      valuePropName="checked"
                      extra="判定页面异常时自动运行该 profile 的初始化剧本复位设备(等当前任务结束后执行)。需 profile 配好 init_action。"
                    >
                      <Switch />
                    </Form.Item>
                  </RuleSection>

                  <RuleSection
                    title="规则 3 · 应用无响应(ANR)"
                    description="仅 gui_android 模式。每个 sample 结束后(含失败/超时)读取设备 ActivityManager 日志,若该 profile 包名出现 ANR(系统自身判定,不受弹窗是否显示影响)则立即触发初始化剧本并报警——启用本规则即视为同意自动复位,不再有单独开关。"
                  >
                    <Form.Item
                      name="anr_check_enabled"
                      label="启用 ANR 检测"
                      valuePropName="checked"
                      extra="只能检测系统自身判定为 ANR 的情况(即使弹窗被厂商 ROM 隐藏也能检测到);无法检测未触发系统 ANR 判定的纯界面卡死。"
                    >
                      <Switch />
                    </Form.Item>
                  </RuleSection>

                  <RuleSection
                    title="定期异常摘要"
                    description="每隔设定小时数,把自上次以来新增的异常汇总(按类型/profile 分组 + 举例)推送到上面的 DingTalk webhook。这段周期内没有新异常则跳过不发。"
                  >
                    <Form.Item
                      name="digest_interval_hours"
                      label="异常摘要间隔 (小时)"
                      extra="0 = 关闭。> 0:每隔该小时数推送一次异常摘要。复用上面的 webhook / secret。"
                    >
                      <InputNumber min={0} max={168} />
                    </Form.Item>
                  </RuleSection>

                  <Space>
                    <Button type="primary" htmlType="submit" loading={saveNotifications.isPending}>
                      保存
                    </Button>
                    <Button
                      onClick={() => void handleTestNotify()}
                      loading={testNotifications.isPending}
                    >
                      发送测试消息
                    </Button>
                    <Button
                      loading={backfillAnomalies.isPending}
                      onClick={async () => {
                        try {
                          const r = await backfillAnomalies.mutateAsync()
                          message.success(`扫描 ${r.scanned} 条,新增 ${r.created} 条异常`)
                        } catch (e) {
                          message.error((e as Error).message)
                        }
                      }}
                    >
                      扫描历史生成异常
                    </Button>
                  </Space>
                  {notifyTestMsg ? (
                    <Alert
                      style={{ marginTop: 12 }}
                      type={notifyTestOk ? 'success' : 'error'}
                      showIcon
                      message={notifyTestMsg}
                    />
                  ) : null}
                </Form>
              </Card>
            ),
          },
          {
            key: 'whitelist',
            label: '白名单',
            children: (
              <Card
                title="重复响应白名单"
                size="small"
                extra={
                  <Button
                    size="small"
                    loading={whitelist.isFetching}
                    onClick={() => whitelist.refetch()}
                  >
                    刷新
                  </Button>
                }
              >
                <Alert
                  style={{ marginBottom: 12 }}
                  type="info"
                  showIcon
                  message="规则 2 命中且 VLM 判定页面正常时,响应会被自动加入这里,后续同样的响应不再触发判断/告警。也可以手动新增(比如提前知道某个响应就是正常的)。"
                />
                {whitelist.isError ? (
                  <Alert
                    type="error"
                    showIcon
                    message="白名单加载失败"
                    description={(whitelist.error as Error)?.message}
                    action={
                      <Button
                        size="small"
                        loading={whitelist.isFetching}
                        onClick={() => whitelist.refetch()}
                      >
                        重试
                      </Button>
                    }
                  />
                ) : (
                  <ResponseListPanel
                    entries={whitelist.data}
                    addPending={addWhitelist.isPending}
                    removePending={removeWhitelist.isPending}
                    onAdd={(values) => addWhitelist.mutateAsync(values)}
                    onRemove={(entry) => removeWhitelist.mutateAsync(entry)}
                    emptyText="还没有白名单记录"
                    addButtonLabel="新增白名单"
                    addModalTitle="新增白名单记录"
                  />
                )}
              </Card>
            ),
          },
          {
            key: 'blacklist',
            label: '黑名单',
            children: (
              <Card
                title="重复响应黑名单"
                size="small"
                extra={
                  <Button
                    size="small"
                    loading={blacklist.isFetching}
                    onClick={() => blacklist.refetch()}
                  >
                    刷新
                  </Button>
                }
              >
                <Alert
                  style={{ marginBottom: 12 }}
                  type="warning"
                  showIcon
                  message="命中黑名单的响应会跳过规则 2 的连续次数等待和 VLM 判断,第一次出现就直接告警(并按同一开关触发自动复位)。仅支持手动新增——确认过某个响应确实是异常后,把它加进来。"
                />
                {blacklist.isError ? (
                  <Alert
                    type="error"
                    showIcon
                    message="黑名单加载失败"
                    description={(blacklist.error as Error)?.message}
                    action={
                      <Button
                        size="small"
                        loading={blacklist.isFetching}
                        onClick={() => blacklist.refetch()}
                      >
                        重试
                      </Button>
                    }
                  />
                ) : (
                  <ResponseListPanel
                    entries={blacklist.data}
                    addPending={addBlacklist.isPending}
                    removePending={removeBlacklist.isPending}
                    onAdd={(values) => addBlacklist.mutateAsync(values)}
                    onRemove={(entry) => removeBlacklist.mutateAsync(entry)}
                    emptyText="还没有黑名单记录"
                    addButtonLabel="新增黑名单"
                    addModalTitle="新增黑名单记录"
                  />
                )}
              </Card>
            ),
          },
          {
            key: 'update',
            label: '系统更新',
            children: <SystemUpdatePanel />,
          },
        ]}
      />
    </div>
  )
}
