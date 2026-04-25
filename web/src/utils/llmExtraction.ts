export function hasLLMExtractionData(
  llmResponses?: Array<string | null>,
  llmErrors?: Array<string | null>,
) {
  return (llmResponses?.length ?? 0) > 0 || (llmErrors?.length ?? 0) > 0
}
