import { Alert, Card, Col, Row, Typography } from 'antd'

interface ResponseComparisonProps {
  ruleResponse?: string
  llmResponse?: string | null
  llmError?: string | null
  llmEnabled: boolean
}

function renderLLMBody({
  llmEnabled,
  llmResponse,
  llmError,
}: Omit<ResponseComparisonProps, 'ruleResponse'>) {
  if (!llmEnabled) {
    return (
      <Alert
        type="info"
        showIcon
        message="未启用 LLM 提取"
        description="当前结果没有 llm_responses / llm_errors，通常表示这个 profile 还没有配置 LLM 响应抽取。"
      />
    )
  }

  if (llmError) {
    return (
      <Alert
        type="warning"
        showIcon
        message="LLM 提取失败"
        description={`错误阶段: ${llmError}`}
      />
    )
  }

  if (llmResponse && llmResponse.trim()) {
    return <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>{llmResponse}</Typography.Paragraph>
  }

  return (
    <Alert
      type="info"
      showIcon
      message="LLM 已启用，但本轮没有提取到文本"
      description="这通常说明接口可用，但该轮没有产出可展示的抽取结果。"
    />
  )
}

export function ResponseComparison({
  ruleResponse,
  llmResponse,
  llmError,
  llmEnabled,
}: ResponseComparisonProps) {
  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} lg={12}>
        <Card size="small" title="规则提取">
          <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>
            {ruleResponse || '(无响应)'}
          </Typography.Paragraph>
        </Card>
      </Col>
      <Col xs={24} lg={12}>
        <Card size="small" title="LLM 提取">
          {renderLLMBody({ llmEnabled, llmResponse, llmError })}
        </Card>
      </Col>
    </Row>
  )
}
