import { App, Button, Card, Form, Input, Typography } from 'antd'
import { useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { SESSION_EXPIRED_KEY } from '../api/client'
import { useLogin } from '../api/auth'
import { useAuth } from '../hooks/useAuth'

interface FormValues {
  username: string
  password: string
}

export function Login() {
  const navigate = useNavigate()
  // RequireAuth stores the full target path as a string in state.from; older
  // bookmarks / direct visits may have no state at all, so fall back to /.
  const location = useLocation() as { state?: { from?: string | { pathname?: string } } }
  const { isAuthenticated, login } = useAuth()
  const mutation = useLogin()
  const { message } = App.useApp()

  const redirectTarget =
    typeof location.state?.from === 'string'
      ? location.state.from
      : (location.state?.from?.pathname ?? '/')
  // Guard against /login bouncing back to /login if the captured target is
  // itself the login page.
  const safeTarget = redirectTarget.startsWith('/login') ? '/' : redirectTarget

  useEffect(() => {
    if (isAuthenticated) {
      navigate(safeTarget, { replace: true })
    }
  }, [isAuthenticated, navigate, safeTarget])

  useEffect(() => {
    if (sessionStorage.getItem(SESSION_EXPIRED_KEY)) {
      sessionStorage.removeItem(SESSION_EXPIRED_KEY)
      message.warning('登录已过期,请重新登录')
    }
    // Only ever check once on mount — this flag exists specifically to
    // survive the hard-redirect that follows a mid-session 401.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const onFinish = async (values: FormValues) => {
    try {
      const response = await mutation.mutateAsync(values)
      login(response.token)
      navigate(safeTarget, { replace: true })
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
