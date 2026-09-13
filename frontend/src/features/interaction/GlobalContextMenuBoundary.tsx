import { useEffect, type ReactNode } from 'react'

export function GlobalContextMenuBoundary({ children }: { children: ReactNode }) {
  useEffect(() => {
    let rightPointerId: number | null = null
    let rightSource: HTMLElement | null = null

    const preventContextMenu = (event: Event) => event.preventDefault()

    const clonePointerToSource = (type: 'pointermove' | 'pointerup' | 'pointercancel', event: PointerEvent) => {
      if (!rightSource || rightPointerId !== event.pointerId) return
      rightSource.dispatchEvent(new PointerEvent(type, {
        bubbles: true,
        cancelable: true,
        pointerId: event.pointerId,
        pointerType: event.pointerType,
        isPrimary: event.isPrimary,
        button: event.button,
        buttons: event.buttons,
        clientX: event.clientX,
        clientY: event.clientY,
        screenX: event.screenX,
        screenY: event.screenY,
        ctrlKey: event.ctrlKey,
        shiftKey: event.shiftKey,
        altKey: event.altKey,
        metaKey: event.metaKey,
      }))
    }

    const pointerDown = (event: PointerEvent) => {
      if (!event.isTrusted || event.button !== 2) return
      // Suppress the browser's native secondary-button gesture from the first
      // event. Chromium can otherwise interrupt pointer capture before DID has
      // completed a right-drag.
      event.preventDefault()
      rightPointerId = event.pointerId
      rightSource = (event.target as Element | null)?.closest<HTMLElement>('[role="treeitem"][data-drop-id]') ?? null
    }

    const pointerMove = (event: PointerEvent) => {
      if (!event.isTrusted || rightPointerId !== event.pointerId || !rightSource) return
      // Route the physical secondary-button stream back through the resource
      // that started the gesture. This keeps right-drag deterministic even on
      // platforms where native context-menu handling drops pointer capture.
      event.stopPropagation()
      clonePointerToSource('pointermove', event)
    }

    const pointerUp = (event: PointerEvent) => {
      if (!event.isTrusted || rightPointerId !== event.pointerId || !rightSource) return
      event.stopPropagation()
      const source = rightSource
      clonePointerToSource('pointerup', event)
      rightPointerId = null
      rightSource = null
      if (source.hasPointerCapture(event.pointerId)) source.releasePointerCapture(event.pointerId)
    }

    const pointerCancel = (event: PointerEvent) => {
      if (!event.isTrusted || rightPointerId !== event.pointerId || !rightSource) return
      event.stopPropagation()
      clonePointerToSource('pointercancel', event)
      rightPointerId = null
      rightSource = null
    }

    document.addEventListener('pointerdown', pointerDown, { capture: true })
    document.addEventListener('pointermove', pointerMove, { capture: true })
    document.addEventListener('pointerup', pointerUp, { capture: true })
    document.addEventListener('pointercancel', pointerCancel, { capture: true })
    document.addEventListener('contextmenu', preventContextMenu, { capture: true })
    return () => {
      document.removeEventListener('pointerdown', pointerDown, { capture: true })
      document.removeEventListener('pointermove', pointerMove, { capture: true })
      document.removeEventListener('pointerup', pointerUp, { capture: true })
      document.removeEventListener('pointercancel', pointerCancel, { capture: true })
      document.removeEventListener('contextmenu', preventContextMenu, { capture: true })
    }
  }, [])
  return <>{children}</>
}
