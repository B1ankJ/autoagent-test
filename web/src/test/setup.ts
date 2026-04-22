import '@testing-library/jest-dom'

if (typeof window !== 'undefined') {
  const current = window.localStorage as Partial<Storage> | undefined
  if (
    !current ||
    typeof current.getItem !== 'function' ||
    typeof current.setItem !== 'function' ||
    typeof current.removeItem !== 'function' ||
    typeof current.clear !== 'function'
  ) {
    const store = new Map<string, string>()
    const mockStorage: Storage = {
      getItem: (key) => store.get(key) ?? null,
      setItem: (key, value) => {
        store.set(key, value)
      },
      removeItem: (key) => {
        store.delete(key)
      },
      clear: () => {
        store.clear()
      },
      key: (index) => Array.from(store.keys())[index] ?? null,
      get length() {
        return store.size
      },
    }

    Object.defineProperty(window, 'localStorage', {
      value: mockStorage,
      configurable: true,
    })
  }

  if (typeof window.matchMedia !== 'function') {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: (query: string): MediaQueryList => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      }),
    })
  }

  const originalGetComputedStyle = window.getComputedStyle.bind(window)
  Object.defineProperty(window, 'getComputedStyle', {
    configurable: true,
    value: (element: Element, pseudoElt?: string) => {
      if (pseudoElt) {
        return originalGetComputedStyle(element)
      }
      return originalGetComputedStyle(element, pseudoElt)
    },
  })
}
