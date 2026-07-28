import Editor from '@monaco-editor/react'

import './monacoSetup'

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
