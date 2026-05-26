import Editor, { loader } from '@monaco-editor/react'
import * as monaco from 'monaco-editor'
import editorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'
import yamlWorker from 'monaco-editor/esm/vs/language/json/json.worker?worker'

// Bundle Monaco locally instead of fetching from jsdelivr CDN at runtime.
loader.config({ monaco })

self.MonacoEnvironment = {
  getWorker(_workerId, label) {
    if (label === 'yaml' || label === 'json') return new yamlWorker()
    return new editorWorker()
  },
}

interface Props {
  value: string
  onChange: (value: string) => void
  height?: number | string
}

export function YamlEditor({ value, onChange, height = 400 }: Props) {
  return (
    <div style={{ border: '1px solid #d9d9d9', borderRadius: 4 }}>
      <Editor
        height={height}
        defaultLanguage="yaml"
        value={value}
        onChange={(nextValue) => onChange(nextValue ?? '')}
        options={{ minimap: { enabled: false }, fontSize: 13, tabSize: 2 }}
      />
    </div>
  )
}
