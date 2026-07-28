import Editor from '@monaco-editor/react'
import type * as monacoNS from 'monaco-editor'

import { monaco } from './monacoSetup'

const LANGUAGE_ID = 'autoagent-log'
const THEME_ID = 'autoagent-log-theme'

// Guard so re-mounting LogViewer (e.g. navigating away and back) doesn't
// re-register the same language/theme with Monaco's global registries.
let registered = false

function registerLogLanguageOnce() {
  if (registered) return
  registered = true

  monaco.languages.register({ id: LANGUAGE_ID })
  // Token-level highlighting (timestamps, log levels, traceback frames) —
  // matches this app's own log line shape ("%(asctime)s %(levelname)s
  // %(name)s - %(message)s", see utils/logging.py) plus uvicorn's
  // "LEVEL:     message" lines and raw Python tracebacks, since
  // Settings.log_file is the whole process's stdout+stderr, not just this
  // app's own logger output.
  monaco.languages.setMonarchTokensProvider(LANGUAGE_ID, {
    tokenizer: {
      root: [
        [/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}[,.]\d+/, 'log-timestamp'],
        [/Traceback \(most recent call last\):/, 'log-error'],
        [/^\s+File "[^"]*", line \d+.*/, 'log-trace-frame'],
        [/\b(CRITICAL|ERROR)\b/, 'log-error'],
        [/\b(WARNING|WARN)\b/, 'log-warning'],
        [/\bINFO\b/, 'log-info'],
        [/\bDEBUG\b/, 'log-debug'],
      ],
    },
  })

  monaco.editor.defineTheme(THEME_ID, {
    base: 'vs',
    inherit: true,
    rules: [
      { token: 'log-timestamp', foreground: '8c8c8c' },
      { token: 'log-error', foreground: 'cf1322', fontStyle: 'bold' },
      { token: 'log-warning', foreground: 'd48806', fontStyle: 'bold' },
      { token: 'log-info', foreground: '1677ff' },
      { token: 'log-debug', foreground: 'a0a0a0' },
      { token: 'log-trace-frame', foreground: '8c8c8c', fontStyle: 'italic' },
    ],
    colors: {},
  })
}

interface Props {
  value: string
  height?: number | string
  onMount?: (editor: monacoNS.editor.IStandaloneCodeEditor) => void
}

/** Read-only, syntax-highlighted log viewer — same Monaco engine VSCode
 * itself uses, so opening a log here looks and feels like opening a file
 * in an editor rather than a plain `<pre>` dump. */
export function LogViewer({ value, height = 560, onMount }: Props) {
  registerLogLanguageOnce()
  return (
    <div style={{ border: '1px solid #d9d9d9', borderRadius: 4 }}>
      <Editor
        height={height}
        language={LANGUAGE_ID}
        theme={THEME_ID}
        value={value}
        onMount={onMount}
        options={{
          readOnly: true,
          domReadOnly: true,
          minimap: { enabled: false },
          fontSize: 12,
          lineNumbers: 'on',
          wordWrap: 'on',
          scrollBeyondLastLine: false,
          renderLineHighlight: 'none',
        }}
      />
    </div>
  )
}
