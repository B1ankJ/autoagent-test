import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Form,
  Input,
  message,
  Radio,
  Row,
  Select,
  Space,
  Spin,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { client } from '../../api/client'
import { useVLM } from '../../api/config'
import {
  useCloseWebBuilderSession,
  useClearSelection,
  useCreateWebBuilderSession,
  useGenerateWebProfile,
  usePickElement,
  useWebBuilderScreenshot,
  useWebBuilderSession,
} from '../../api/webProfileBuilder'

const { Text } = Typography

type PickField = 'input' | 'send' | 'response' | 'ready_check' | 'new_session'

const FIELD_LABELS: Record<PickField, string> = {
  input: '输入框',
  send: '发送按钮/区域',
  response: '回复容器',
  ready_check: '就绪检测元素',
  new_session: '新建对话按钮',
}

const FIELD_COLORS: Record<PickField, string> = {
  input: 'blue',
  send: 'green',
  response: 'purple',
  ready_check: 'orange',
  new_session: 'cyan',
}

const ALL_FIELDS: PickField[] = ['input', 'send', 'response', 'ready_check', 'new_session']
const REQUIRED_FIELDS: PickField[] = ['input', 'send', 'response']

export default function WebBuilder() {
  const navigate = useNavigate()
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [pickingField, setPickingField] = useState<PickField | null>(null)
  const [sendType, setSendType] = useState<'keyboard' | 'click'>('keyboard')
  const [keyboardKey, setKeyboardKey] = useState('Enter')
  const [generatedYaml, setGeneratedYaml] = useState<string | null>(null)
  const [profileName, setProfileName] = useState('')
  const imgRef = useRef<HTMLImageElement>(null)
  const [startForm] = Form.useForm()

  const createSession = useCreateWebBuilderSession()
  const { data: session } = useWebBuilderSession(sessionId)
  const {
    data: screenshotData,
    isFetching: screenshotLoading,
    refetch: refetchScreenshot,
  } = useWebBuilderScreenshot(sessionId, !!sessionId)
  const pickElement = usePickElement(sessionId ?? '')
  const clearSel = useClearSelection(sessionId ?? '')
  const generateProfile = useGenerateWebProfile(sessionId ?? '')
  const closeSession = useCloseWebBuilderSession()
  const { data: vlm } = useVLM()
  const vlmReady = !!(vlm?.base_url && vlm?.model && vlm?.api_key)
  const [injectLlm, setInjectLlm] = useState(false)

  async function handleStart(values: { url: string; channel: string; user_data_dir?: string }) {
    try {
      const s = await createSession.mutateAsync({
        url: values.url,
        channel: values.channel || 'chromium',
        headless: false,
        user_data_dir: values.user_data_dir || null,
      })
      setSessionId(s.id)
    } catch (e: unknown) {
      message.error(`启动失败: ${(e as Error).message}`)
    }
  }

  async function handleImageClick(e: React.MouseEvent<HTMLImageElement>) {
    if (!pickingField || !sessionId || !imgRef.current) return
    const rect = imgRef.current.getBoundingClientRect()
    const scaleX = imgRef.current.naturalWidth / rect.width
    const scaleY = imgRef.current.naturalHeight / rect.height
    const x = (e.clientX - rect.left) * scaleX
    const y = (e.clientY - rect.top) * scaleY
    try {
      const result = await pickElement.mutateAsync({
        field: pickingField,
        x,
        y,
        send_type: pickingField === 'send' ? sendType : undefined,
        keyboard_key:
          pickingField === 'send' && sendType === 'keyboard' ? keyboardKey : undefined,
      })
      message.success(`已捕获「${FIELD_LABELS[pickingField]}」: ${result.selector}`)
      setPickingField(null)
      refetchScreenshot()
    } catch (e: unknown) {
      message.error(`捕获失败: ${(e as Error).message}`)
    }
  }

  async function handleGenerate() {
    if (!profileName.trim()) {
      message.warning('请先填写 Profile 名称')
      return
    }
    try {
      const result = await generateProfile.mutateAsync({
        name: profileName.trim(),
        stable_sec: 5,
        ready_timeout_sec: 15,
        inject_llm: injectLlm,
      })
      setGeneratedYaml(result.yaml)
    } catch (e: unknown) {
      message.error(`生成失败: ${(e as Error).message}`)
    }
  }

  async function handleSave() {
    if (!generatedYaml || !profileName.trim()) return
    try {
      await client.put(`/profiles/${profileName.trim()}`, { yaml: generatedYaml })
      message.success('Profile 已保存')
      if (sessionId) await closeSession.mutateAsync(sessionId)
      navigate('/profiles')
    } catch (e: unknown) {
      message.error(`保存失败: ${(e as Error).message}`)
    }
  }

  async function handleClose() {
    if (sessionId) await closeSession.mutateAsync(sessionId)
    setSessionId(null)
    setGeneratedYaml(null)
    setPickingField(null)
  }

  const selections = session?.selections ?? {}
  const requiredDone = REQUIRED_FIELDS.every((f) => f in selections)

  // ── Start screen ────────────────────────────────────────────────────────────
  if (!sessionId) {
    return (
      <div style={{ maxWidth: 600, margin: '24px auto 0' }}>
        <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
          填写目标网址,启动浏览器后在截图上点击各元素完成配置,无需手动写 YAML。
        </Text>
        <Card size="small">
          <Form form={startForm} layout="vertical" onFinish={handleStart}>
            <Form.Item
              label="目标 URL"
              name="url"
              rules={[{ required: true, message: '请输入 URL' }]}
            >
              <Input placeholder="https://example.com" />
            </Form.Item>
            <Form.Item label="浏览器" name="channel" initialValue="chromium">
              <Select>
                <Select.Option value="chromium">Chromium（内置）</Select.Option>
                <Select.Option value="chrome">Chrome（系统安装）</Select.Option>
              </Select>
            </Form.Item>
            <Form.Item
              label="用户数据目录（可选，复用登录态）"
              name="user_data_dir"
            >
              <Input placeholder="/Users/xxx/Library/Application Support/Google/ChromePlaywright" />
            </Form.Item>
            <Form.Item>
              <Button type="primary" htmlType="submit" loading={createSession.isPending}>
                启动浏览器
              </Button>
            </Form.Item>
          </Form>
        </Card>
      </div>
    )
  }

  // ── Builder screen ───────────────────────────────────────────────────────────
  return (
    <div style={{ padding: 24 }}>
      <Row gutter={16} align="top">
        {/* screenshot panel */}
        <Col span={16}>
          <Card
            title="页面截图"
            extra={
              <Space>
                <Button size="small" onClick={() => refetchScreenshot()} loading={screenshotLoading}>
                  刷新截图
                </Button>
                <Button size="small" danger onClick={handleClose} loading={closeSession.isPending}>
                  关闭会话
                </Button>
              </Space>
            }
          >
            {!screenshotData ? (
              <Spin tip="加载截图..." style={{ display: 'block', padding: 40 }} />
            ) : (
              <div
                style={{ cursor: pickingField ? 'crosshair' : 'default', userSelect: 'none' }}
              >
                {pickingField && (
                  <Alert
                    style={{ marginBottom: 8 }}
                    type="info"
                    message={`点击页面上的「${FIELD_LABELS[pickingField]}」`}
                    showIcon
                  />
                )}
                <img
                  ref={imgRef}
                  src={`data:image/png;base64,${screenshotData.image}`}
                  alt="page screenshot"
                  style={{ width: '100%', border: '1px solid #d9d9d9', borderRadius: 4 }}
                  onClick={handleImageClick}
                />
              </div>
            )}
          </Card>
        </Col>

        {/* controls panel */}
        <Col span={8}>
          <Space direction="vertical" style={{ width: '100%' }} size={12}>
            {/* element capture */}
            <Card title="元素捕获" size="small">
              <Space direction="vertical" style={{ width: '100%' }}>
                {ALL_FIELDS.map((field) => {
                  const done = field in selections
                  const sel = selections[field]
                  return (
                    <div key={field} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <Tag color={done ? FIELD_COLORS[field] : 'default'} style={{ minWidth: 86 }}>
                        {FIELD_LABELS[field]}
                      </Tag>
                      {done ? (
                        <Tooltip title={sel?.selector}>
                          <Text
                            code
                            style={{
                              fontSize: 11,
                              flex: 1,
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                              display: 'block',
                              maxWidth: 100,
                            }}
                          >
                            {sel?.selector}
                          </Text>
                        </Tooltip>
                      ) : (
                        <Text type="secondary" style={{ fontSize: 12, flex: 1 }}>
                          未选择
                        </Text>
                      )}
                      <Button
                        size="small"
                        type={pickingField === field ? 'primary' : 'default'}
                        onClick={() => setPickingField(pickingField === field ? null : field)}
                      >
                        {pickingField === field ? '取消' : done ? '重选' : '选择'}
                      </Button>
                      {done && (
                        <Button size="small" danger onClick={() => clearSel.mutate(field)}>
                          ✕
                        </Button>
                      )}
                    </div>
                  )
                })}

                {/* send method options when picking send */}
                {pickingField === 'send' && (
                  <Card size="small" style={{ marginTop: 4 }}>
                    <Form.Item label="发送方式" style={{ marginBottom: 8 }}>
                      <Radio.Group
                        value={sendType}
                        onChange={(e) => setSendType(e.target.value as 'keyboard' | 'click')}
                      >
                        <Radio value="keyboard">键盘</Radio>
                        <Radio value="click">点击</Radio>
                      </Radio.Group>
                    </Form.Item>
                    {sendType === 'keyboard' && (
                      <Form.Item label="按键" style={{ marginBottom: 0 }}>
                        <Input
                          size="small"
                          value={keyboardKey}
                          onChange={(e) => setKeyboardKey(e.target.value)}
                          style={{ width: 100 }}
                        />
                      </Form.Item>
                    )}
                  </Card>
                )}
              </Space>
            </Card>

            {/* generate */}
            <Card title="生成 YAML" size="small">
              <Space direction="vertical" style={{ width: '100%' }}>
                <Input
                  placeholder="Profile 名称（如 my_site）"
                  value={profileName}
                  onChange={(e) => setProfileName(e.target.value)}
                />
                <div>
                  <Tooltip title={vlmReady ? '' : '请先在「配置」页填写完整 VLM 凭据'}>
                    <Checkbox
                      checked={injectLlm}
                      disabled={!vlmReady}
                      onChange={(e) => setInjectLlm(e.target.checked)}
                    >
                      生成时注入 LLM 响应抽取配置
                    </Checkbox>
                  </Tooltip>
                </div>
                <Button
                  type="primary"
                  block
                  disabled={!requiredDone}
                  loading={generateProfile.isPending}
                  onClick={handleGenerate}
                >
                  生成 YAML 草稿
                </Button>
                {!requiredDone && (
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    需先选择：输入框、发送、回复容器
                  </Text>
                )}
              </Space>
            </Card>

            {/* yaml preview */}
            {generatedYaml && (
              <Card
                title="YAML 草稿"
                size="small"
                extra={
                  <Button type="primary" size="small" onClick={handleSave}>
                    保存 Profile
                  </Button>
                }
              >
                <Input.TextArea
                  value={generatedYaml}
                  onChange={(e) => setGeneratedYaml(e.target.value)}
                  rows={18}
                  style={{ fontFamily: 'monospace', fontSize: 12 }}
                />
              </Card>
            )}
          </Space>
        </Col>
      </Row>
    </div>
  )
}
