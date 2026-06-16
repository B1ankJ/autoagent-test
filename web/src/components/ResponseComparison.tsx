import { Alert, Card, Col, Row, Space, Tag, Typography } from 'antd'

interface ResponseComparisonProps {
  ruleResponse?: string
  llmResponse?: string | null
  llmError?: string | null
  llmEnabled: boolean
}

// Mirror of openai_compat.chat_completions.select_message_content:
// LLM wins only when enabled, no error, AND the text is non-empty.
function pickActuallyReturned({
  llmEnabled,
  llmResponse,
  llmError,
}: Omit<ResponseComparisonProps, 'ruleResponse'>): 'rule' | 'llm' {
  if (llmEnabled && !llmError && llmResponse && llmResponse.trim()) {
    return 'llm'
  }
  return 'rule'
}

function ReturnedTag() {
  return (
    <Tag color="green" style={{ marginInlineStart: 0 }}>
      实际返回
    </Tag>
  )
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
        description="当前 profile 没有配置 LLM 响应抽取。主响应直接作为返回结果。"
      />
    )
  }

  if (llmError) {
    return (
      <Alert
        type="warning"
        showIcon
        message="LLM 提取失败"
        description={`错误阶段: ${llmError}。已自动回退到主响应。`}
      />
    )
  }

  if (llmResponse && llmResponse.trim()) {
    return (
      <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>
        {llmResponse}
      </Typography.Paragraph>
    )
  }

  return (
    <Alert
      type="info"
      showIcon
      message="LLM 已启用，但本轮没有提取到文本"
      description="LLM 接口可用但无文本产出，已回退到主响应。"
    />
  )
}

export function ResponseComparison({
  ruleResponse,
  llmResponse,
  llmError,
  llmEnabled,
}: ResponseComparisonProps) {
  const returned = pickActuallyReturned({ llmEnabled, llmResponse, llmError })
  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} lg={12}>
        <Card
          size="small"
          title={
            <Space size={8}>
              <span>主响应（responses）</span>
              {returned === 'rule' ? <ReturnedTag /> : null}
            </Space>
          }
        >
          <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>
            {ruleResponse || '(主链路未产出文本)'}
          </Typography.Paragraph>
        </Card>
      </Col>
      <Col xs={24} lg={12}>
        <Card
          size="small"
          title={
            <Space size={8}>
              <span>LLM 复核（llm_responses）</span>
              {returned === 'llm' ? <ReturnedTag /> : null}
            </Space>
          }
        >
          {renderLLMBody({ llmEnabled, llmResponse, llmError })}
        </Card>
      </Col>
    </Row>
  )
}
