/**
 * Splits a textarea's raw text into prompts, using a blank line as the
 * separator between prompts. A single newline stays inside the same prompt,
 * so a prompt that itself needs multiple lines can be typed directly instead
 * of being silently cut into several prompts.
 */
export function splitPrompts(text: string): string[] {
  return text
    .replace(/\r\n/g, '\n')
    .split(/\n[ \t]*\n+/)
    .map((s) => s.trim())
    .filter(Boolean)
}
