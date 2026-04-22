import { client } from './client'
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

export async function fetchScreenshotBlobUrl(
  batchId: string,
  sampleId: string,
  name: string,
): Promise<string> {
  const { data } = await client.get<Blob>(
    `/batches/${batchId}/samples/${sampleId}/screenshots/${encodeURIComponent(name)}`,
    { responseType: 'blob' },
  )
  return URL.createObjectURL(data)
}

export function screenshotPath(batchId: string, sampleId: string, name: string): string {
  return `/api/v1/batches/${batchId}/samples/${sampleId}/screenshots/${encodeURIComponent(name)}`
}
