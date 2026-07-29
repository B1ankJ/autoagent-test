/** Formats a millisecond duration for display: "850ms" below 1s, "12.3s"
 * below 1min, "2m 5s" above that. Shared between Profiles List's average-
 * duration column and Batches List's duration column/anomaly highlight. */
export function formatDurationMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`
  const totalSeconds = ms / 1000
  if (totalSeconds < 60) return `${totalSeconds.toFixed(1)}s`
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = Math.round(totalSeconds % 60)
  return `${minutes}m ${seconds}s`
}
