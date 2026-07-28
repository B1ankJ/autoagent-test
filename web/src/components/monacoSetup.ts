import { loader } from '@monaco-editor/react'
import * as monaco from 'monaco-editor'
import editorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'
import yamlWorker from 'monaco-editor/esm/vs/language/json/json.worker?worker'

// Bundle Monaco locally instead of fetching from jsdelivr CDN at runtime.
// Shared by every Monaco-based editor/viewer in the app (YamlEditor,
// LogViewer) so this only runs once regardless of which one mounts first.
loader.config({ monaco })

self.MonacoEnvironment = {
  getWorker(_workerId, label) {
    if (label === 'yaml' || label === 'json') return new yamlWorker()
    return new editorWorker()
  },
}

export { monaco }
