const STORAGE_KEY = 'autoagent_preload_reloaded'

/**
 * A tab left open across a deploy still has the old index.html's chunk
 * hashes baked into its lazy import() calls (e.g. YamlEditor/LogViewer's
 * React.lazy) — once the server's static/assets/ has been overwritten by a
 * new build, fetching those old-hashed files 404s with "Failed to fetch
 * dynamically imported module". Vite fires 'vite:preloadError' for exactly
 * that case; reload once to pick up the fresh index.html + current chunk
 * hashes instead of leaving the user stuck on ErrorBoundary's manual 刷新
 * button.
 *
 * Guarded via sessionStorage so a genuinely broken deploy doesn't
 * reload-loop forever — call clearReloadGuard() once per successful boot
 * so the next real deploy still gets one automatic retry. Returns an
 * unsubscribe function (mainly for tests; the app itself never tears this
 * down).
 */
export function installStaleChunkReload(): () => void {
  const handler = (event: Event) => {
    if (sessionStorage.getItem(STORAGE_KEY)) return
    sessionStorage.setItem(STORAGE_KEY, '1')
    event.preventDefault()
    window.location.reload()
  }
  window.addEventListener('vite:preloadError', handler)
  return () => window.removeEventListener('vite:preloadError', handler)
}

export function clearReloadGuard(): void {
  sessionStorage.removeItem(STORAGE_KEY)
}
