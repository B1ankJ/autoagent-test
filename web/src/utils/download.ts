export function parseContentDisposition(header: string | undefined): string | null {
  if (!header) {
    return null
  }

  const match = /filename\*?=(?:UTF-8'')?["']?([^"';]+)["']?/i.exec(header)
  return match ? decodeURIComponent(match[1]) : null
}

export function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}
