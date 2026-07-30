import { loader } from '@monaco-editor/react'
// `monaco-editor`'s default barrel (`import * as monaco from 'monaco-editor'`)
// registers every bundled language as a side effect — including the
// typescript, html, and css/less/scss language *services*, each of which
// ships its own multi-MB worker (ts.worker alone was ~7MB unminified) even
// though nothing in this app edits any of those languages. Importing the
// core editor API directly avoids pulling those in; only the `yaml` basic
// language (a lightweight Monarch tokenizer, no dedicated worker) is
// registered explicitly since YamlEditor sets `defaultLanguage="yaml"`.
// LogViewer's "autoagent-log" language is registered manually at runtime
// and needs no bundled language contribution.
import * as monaco from 'monaco-editor/esm/vs/editor/editor.api'
import 'monaco-editor/esm/vs/basic-languages/yaml/yaml.contribution'
import editorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'

// Bundle Monaco locally instead of fetching from jsdelivr CDN at runtime.
// Shared by every Monaco-based editor/viewer in the app (YamlEditor,
// LogViewer) so this only runs once regardless of which one mounts first.
loader.config({ monaco })

self.MonacoEnvironment = {
  getWorker() {
    // The base editor worker (find/replace, word suggestions, diffing)
    // covers every language used in this app — none of them (yaml, the
    // custom log language) has its own dedicated language-service worker.
    return new editorWorker()
  },
}

export { monaco }
