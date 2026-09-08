import { useEffect } from 'react'

/** Applies dark mode from Electron's nativeTheme (via preload), falling back to
 *  the OS media query when running the renderer outside Electron (plain `vite`).
 *  UI-only state -- lives in the DOM, not a store. */
export function useTheme() {
  useEffect(() => {
    const apply = (dark: boolean) =>
      document.documentElement.classList.toggle('dark', dark)

    const bridge = window.desktop
    if (bridge) {
      apply(bridge.shouldUseDarkColors())
      return bridge.onThemeChange(apply)
    }

    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    apply(mq.matches)
    const handler = (e: MediaQueryListEvent) => apply(e.matches)
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])
}

declare global {
  interface Window {
    desktop?: {
      shouldUseDarkColors: () => boolean
      onThemeChange: (cb: (dark: boolean) => void) => () => void
    }
  }
}
