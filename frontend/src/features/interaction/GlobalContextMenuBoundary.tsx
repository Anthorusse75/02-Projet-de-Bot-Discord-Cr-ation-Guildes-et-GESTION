import { useEffect, type ReactNode } from 'react'

export function GlobalContextMenuBoundary({ children }: { children: ReactNode }) {
  useEffect(() => {
    const prevent = (event: Event) => event.preventDefault()
    document.addEventListener('contextmenu', prevent, { capture: true })
    return () => document.removeEventListener('contextmenu', prevent, { capture: true })
  }, [])
  return <>{children}</>
}
