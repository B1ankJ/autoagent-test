import { ArrowLeftOutlined } from '@ant-design/icons'
import { App, Button, Card, Input, Modal, Skeleton, Space } from 'antd'
import { Suspense, lazy, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useProfile, useSaveProfile, useValidateProfile } from '../../api/profiles'
import { PageHeader } from '../../components/states/PageHeader'
import { ConnectivityTestModal } from './ConnectivityTestModal'

// Monaco is ~3 MB. Defer the import so it doesn't land in the initial chunk;
// users on Dashboard/Batches never need it.
const YamlEditor = lazy(() =>
  import('../../components/YamlEditor').then((m) => ({ default: m.YamlEditor })),
)

export function ProfileEdit() {
  const { name: routeName } = useParams()
  const isNew = !routeName
  const navigate = useNavigate()
  const { message } = App.useApp()

  const [name, setName] = useState(routeName ?? '')
  const [yaml, setYaml] = useState('')
  const [testOpen, setTestOpen] = useState(false)

  const { data } = useProfile(routeName)
  const save = useSaveProfile()
  const validate = useValidateProfile()

  useEffect(() => {
    if (data?.yaml) {
      setYaml(data.yaml)
    }
  }, [data])

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
            <a onClick={() => navigate('/profiles')} style={{ color: 'var(--aa-text-muted)' }}>
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
      />
    </div>
  )
}
