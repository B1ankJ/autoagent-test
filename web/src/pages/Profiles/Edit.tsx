import { ArrowLeftOutlined, CheckCircleFilled, CloseCircleFilled } from '@ant-design/icons'
import { Alert, App, Button, Card, Input, Modal, Skeleton, Space, Typography } from 'antd'
import { Suspense, lazy, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useProfile, useSaveProfile, useValidateProfile } from '../../api/profiles'
import { PageHeader } from '../../components/states/PageHeader'
import { ConnectivityTestModal, type ConnectivitySummary } from './ConnectivityTestModal'

// Monaco is ~3 MB. Defer the import so it doesn't land in the initial chunk;
// users on Dashboard/Batches never need it.
const YamlEditor = lazy(() =>
  import('../../components/YamlEditor').then((m) => ({ default: m.YamlEditor })),
)

export function ProfileEdit() {
  const { name: routeName } = useParams()
  const isNew = !routeName
  const navigate = useNavigate()
  const { message, modal } = App.useApp()

  const [name, setName] = useState(routeName ?? '')
  const [yaml, setYaml] = useState('')
  const [testOpen, setTestOpen] = useState(false)
  const [lastConn, setLastConn] = useState<ConnectivitySummary | null>(null)
  // Track YAML snapshot when the connectivity test was run; the result is
  // only meaningful while the YAML is unchanged.
  const [connYamlSnapshot, setConnYamlSnapshot] = useState<string | null>(null)

  const { data } = useProfile(routeName)
  const save = useSaveProfile()
  const validate = useValidateProfile()

  useEffect(() => {
    if (data?.yaml) {
      setYaml(data.yaml)
    }
  }, [data])

  // An existing profile is dirty once its YAML diverges from what loaded;
  // a brand-new one is dirty as soon as either field has anything in it.
  const isDirty = isNew ? name !== '' || yaml !== '' : data?.yaml !== undefined && yaml !== data.yaml

  useEffect(() => {
    if (!isDirty) return
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault()
      // Chrome ignores returnValue's actual text and shows its own generic
      // prompt, but setting it is still required to trigger that prompt at all.
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [isDirty])

  const goToProfiles = () => {
    if (!isDirty) {
      navigate('/profiles')
      return
    }
    modal.confirm({
      title: '放弃未保存的修改?',
      content: '离开当前页面将丢失尚未保存的 YAML 改动。',
      okText: '放弃并离开',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: () => navigate('/profiles'),
    })
  }

  const profileMode = useMemo(() => {
    if (/^platform:\s*android\b/m.test(yaml)) return 'gui_android' as const
    if (/^platform:\s*web\b/m.test(yaml)) return 'gui_pc_web' as const
    if (/^platform:\s*api\b/m.test(yaml)) return 'api' as const
    return null
  }, [yaml])

  const onValidate = async () => {
    const result = await validate.mutateAsync(yaml)
    if (result.ok) {
      message.success('校验通过')
      return
    }

    Modal.error({ title: 'YAML 校验失败', content: result.error ?? '未知错误' })
  }

  const onSave = async () => {
    if (!name) {
      message.error('请输入 profile 名称')
      return
    }

    try {
      await save.mutateAsync({ name, yaml, create: isNew })
      message.success('已保存')
      if (isNew) {
        navigate(`/profiles/${name}`, { replace: true })
      }
    } catch (error) {
      Modal.error({ title: '保存失败', content: (error as Error).message })
    }
  }

  return (
    <div>
      <PageHeader
        eyebrow={
          <Space size={6}>
            <a onClick={goToProfiles} style={{ color: 'var(--aa-text-muted)' }}>
              <ArrowLeftOutlined /> 配置档
            </a>
            <span>/ {isNew ? '新建' : '编辑'}</span>
          </Space>
        }
        title={isNew ? '新建 Profile' : routeName!}
        subtitle={
          isNew ? '填写 YAML 内容,保存后即可用于批次和单次测试。' : '修改后点保存,可在此页直接做连通性测试。'
        }
        extra={
          <>
            <Button onClick={onValidate} loading={validate.isPending}>
              校验
            </Button>
            <Button disabled={isNew || !profileMode} onClick={() => setTestOpen(true)}>
              连通性测试
            </Button>
            <Button type="primary" onClick={onSave} loading={save.isPending}>
              保存
            </Button>
          </>
        }
      />
      {lastConn ? (
        <Alert
          style={{ marginBottom: 12 }}
          showIcon
          icon={lastConn.ok ? <CheckCircleFilled /> : <CloseCircleFilled />}
          type={lastConn.ok ? 'success' : 'error'}
          closable
          onClose={() => {
            setLastConn(null)
            setConnYamlSnapshot(null)
          }}
          message={
            <Space size={10}>
              <span>{lastConn.ok ? '连通正常' : '连通失败'}</span>
              {connYamlSnapshot !== null && connYamlSnapshot !== yaml ? (
                <Typography.Text type="warning" style={{ fontSize: 12 }}>
                  YAML 已修改,需重测
                </Typography.Text>
              ) : null}
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {new Date(lastConn.ts).toLocaleTimeString()}
                {lastConn.durationMs != null ? ` · ${lastConn.durationMs} ms` : ''}
                {' · prompt='}
                <span className="aa-mono">{lastConn.prompt}</span>
              </Typography.Text>
            </Space>
          }
          description={lastConn.ok ? undefined : lastConn.error || undefined}
          action={
            <Button size="small" onClick={() => setTestOpen(true)}>
              重测
            </Button>
          }
        />
      ) : null}
      <Card size="small">
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          {isNew ? (
            <Input
              placeholder="profile 名称(用于文件名,不含空格/中文)"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          ) : null}
          <Suspense fallback={<Skeleton.Input active style={{ width: '100%', height: 400 }} />}>
            <YamlEditor value={yaml} onChange={setYaml} />
          </Suspense>
        </Space>
      </Card>
      <ConnectivityTestModal
        open={testOpen}
        profileName={routeName ?? ''}
        mode={profileMode ?? 'api'}
        onClose={() => setTestOpen(false)}
        onResult={(summary) => {
          setLastConn(summary)
          setConnYamlSnapshot(yaml)
        }}
      />
    </div>
  )
}
