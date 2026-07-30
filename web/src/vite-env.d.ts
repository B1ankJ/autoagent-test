/// <reference types="vite/client" />

// monaco-editor's package.json "exports" map only declares "types" for the
// root specifier ("."), not for deep subpaths like "esm/vs/editor/editor.api"
// (it's covered only by a generic "./*": "./*" passthrough with no types
// condition). We import that lighter entry point directly in monacoSetup.ts
// to avoid bundling every language's worker — this tells TypeScript to type
// it the same as the root package instead of failing to resolve it.
declare module 'monaco-editor/esm/vs/editor/editor.api' {
  export * from 'monaco-editor'
}
