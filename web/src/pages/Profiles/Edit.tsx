import { App, Button, Card, Input, Modal, Space, Typography } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useProfile, useSaveProfile, useValidateProfile } from '../../api/profiles'
import { YamlEditor } from '../../components/YamlEditor'
import { ConnectivityTestModal } from './ConnectivityTestModal'

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
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Typography.Title level={3}>{isNew ? '新建 Profile' : `编辑 ${routeName}`}</Typography.Title>
      <Card>
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          {isNew ? (
            <Input
              placeholder="profile 名称"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          ) : null}
          <YamlEditor value={yaml} onChange={setYaml} />
          <Space>
            <Button onClick={onValidate} loading={validate.isPending}>
              校验
            </Button>
            <Button type="primary" onClick={onSave} loading={save.isPending}>
              保存
            </Button>
            <Button disabled={isNew || !profileMode} onClick={() => setTestOpen(true)}>
              连通性测试
            </Button>
            <Button onClick={() => navigate('/profiles')}>返回</Button>
          </Space>
        </Space>
      </Card>
      <ConnectivityTestModal
        open={testOpen}
        profileName={routeName ?? ''}
        mode={profileMode ?? 'api'}
        onClose={() => setTestOpen(false)}
      />
    </Space>
  )
}
