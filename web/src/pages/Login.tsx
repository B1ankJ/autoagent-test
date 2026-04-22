import { App, Button, Card, Form, Input, Typography } from 'antd'
import { useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useLogin } from '../api/auth'
import { useAuth } from '../hooks/useAuth'

interface FormValues {
  username: string
  password: string
}

export function Login() {
  const navigate = useNavigate()
  const location = useLocation() as { state?: { from?: { pathname: string } } }
  const { isAuthenticated, login } = useAuth()
  const mutation = useLogin()
  const { message } = App.useApp()

  useEffect(() => {
    if (isAuthenticated) {
      navigate(location.state?.from?.pathname ?? '/', { replace: true })
    }
  }, [isAuthenticated, location.state, navigate])

  const onFinish = async (values: FormValues) => {
    try {
      const response = await mutation.mutateAsync(values)
      login(response.token)
      navigate(location.state?.from?.pathname ?? '/', { replace: true })
    } catch (error) {
      message.error((error as Error).message)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#f0f2f5',
      }}
    >
      <Card style={{ width: 360 }}>
        <Typography.Title level={3} style={{ textAlign: 'center' }}>
          AutoAgent Test
        </Typography.Title>
        <Form<FormValues> layout="vertical" onFinish={onFinish}>
          <Form.Item name="username" label="用户名" rules={[{ required: true }]}>
            <Input autoFocus />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true }]}>
            <Input.Password />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={mutation.isPending}>
            登录
          </Button>
        </Form>
      </Card>
    </div>
  )
}
