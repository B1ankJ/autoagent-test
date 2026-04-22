import { Button, Result } from 'antd'
import { Component, ErrorInfo, ReactNode } from 'react'

interface State {
  error: Error | null
}

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('UI crash', error, info)
  }

  render() {
    if (this.state.error) {
      return (
        <Result
          status="error"
          title="页面出错"
          subTitle={this.state.error.message}
          extra={<Button onClick={() => window.location.reload()}>刷新</Button>}
        />
      )
    }

    return this.props.children
  }
}
