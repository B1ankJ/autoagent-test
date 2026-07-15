export function hasLLMExtractionData(
  llmResponses?: Array<string | null>,
  llmErrors?: Array<string | null>,
) {
  return (llmResponses?.length ?? 0) > 0 || (llmErrors?.length ?? 0) > 0
}

interface EffectiveResponseInput {
  ruleResponse?: string
  llmResponse?: string | null
  llmError?: string | null
  llmEnabled: boolean
}

// Mirror of openai_compat.chat_completions.select_message_content: LLM wins
// only when enabled, no error, AND the text is non-empty.
export function pickActuallyReturned({
  llmEnabled,
  llmResponse,
  llmError,
}: Omit<EffectiveResponseInput, 'ruleResponse'>): 'rule' | 'llm' {
  if (llmEnabled && !llmError && llmResponse && llmResponse.trim()) {
    return 'llm'
  }
  return 'rule'
}

/** The single "effective" response text — same priority as ResponseComparison's
 * "实际返回" tag, for call sites that just want one string instead of the
 * side-by-side rule/LLM comparison view (e.g. compact previews). */
export function selectEffectiveResponseText({
  ruleResponse,
  llmResponse,
  llmError,
  llmEnabled,
}: EffectiveResponseInput): string {
  const which = pickActuallyReturned({ llmEnabled, llmResponse, llmError })
  return which === 'llm' && llmResponse ? llmResponse : ruleResponse || ''
}
