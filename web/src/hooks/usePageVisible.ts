import { useEffect, useState } from 'react'

/**
 * True while the tab is foregrounded. Lets components tear down expensive
 * work (video decoders, streams) when the user switches away and resume on
 * return, instead of burning CPU / bandwidth on a hidden tab.
 */
export function usePageVisible(): boolean {
  const [visible, setVisible] = useState(
    typeof document === 'undefined' ? true : !document.hidden,
  )
  useEffect(() => {
    const onChange = () => setVisible(!document.hidden)
    document.addEventListener('visibilitychange', onChange)
    return () => document.removeEventListener('visibilitychange', onChange)
  }, [])
  return visible
}
