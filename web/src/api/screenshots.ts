import { client } from './client'
import { getToken } from './client'
import { ScreenshotInfo } from '../types/api'

export async function listScreenshots(
  batchId: string,
  sampleId: string,
): Promise<ScreenshotInfo[]> {
  const { data } = await client.get<ScreenshotInfo[]>(
    `/batches/${batchId}/samples/${sampleId}/screenshots`,
  )
  return data
}

/**
 * Direct URL for a sample screenshot, usable as an <img src>. Auth rides in
 * the `?token=` query because <img> can't set an Authorization header.
 * Pass `width` for a downscaled JPEG thumbnail (log strip); omit for the
 * full-resolution PNG (zoom).
 */
export function screenshotUrl(
  batchId: string,
  sampleId: string,
  name: string,
  width?: number,
): string {
  const token = getToken() ?? ''
  const params = new URLSearchParams({ token })
  if (width) params.set('w', String(width))
  return `/api/v1/media/batches/${encodeURIComponent(batchId)}/samples/${encodeURIComponent(
    sampleId,
  )}/screenshot/${encodeURIComponent(name)}?${params.toString()}`
}
