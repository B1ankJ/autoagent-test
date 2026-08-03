import { theme } from 'antd'
import { diffWords } from 'diff'
import { useMemo } from 'react'

interface Props {
  before: string
  after: string
}

/** Word-level diff of two strings: words only in `before` are shown removed
 * (error background + strikethrough), words only in `after` are shown added
 * (success background), unchanged words are plain. Theme-aware via AntD
 * tokens so it reads correctly in both light and dark mode. Diff is memoized
 * on the input pair so re-renders don't recompute. */
export function DiffText({ before, after }: Props) {
  const { token } = theme.useToken()
  const parts = useMemo(() => diffWords(before, after), [before, after])

  return (
    <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.7 }}>
      {parts.map((part, i) => {
        if (part.added) {
          return (
            <span key={i} style={{ background: token.colorSuccessBg, color: token.colorSuccess }}>
              {part.value}
            </span>
          )
        }
        if (part.removed) {
          return (
            <span
              key={i}
              style={{
                background: token.colorErrorBg,
                color: token.colorError,
                textDecoration: 'line-through',
              }}
            >
              {part.value}
            </span>
          )
        }
        return <span key={i}>{part.value}</span>
      })}
    </div>
  )
}
