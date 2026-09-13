import { useEffect, type ReactNode } from 'react'

export function GlobalContextMenuBoundary({ children }: { children: ReactNode }) {
  useEffect(() => {
    const preventContextMenu = (event: Event) => event.preventDefault()
    const preventRightButtonDefault = (event: PointerEvent) => {
      // Chromium may dispatch the native context-menu gesture as soon as the
      // secondary button is pressed. Preventing its default action at pointer
      // down keeps the pointer stream available to DID's right-drag gesture
      // engine while still allowing the event to propagate to React handlers.
      if (event.button === 2) event.preventDefault()
    }
    document.addEventListener('pointerdown', preventRightButtonDefault, { capture: true })
    document.addEventListener('contextmenu', preventContextMenu, { capture: true })
    return () => {
      document.removeEventListener('pointerdown', preventRightButtonDefault, { capture: true })
      document.removeEventListener('contextmenu', preventContextMenu, { capture: true })
    }
  }, [])
  return <>{children}</>
}
