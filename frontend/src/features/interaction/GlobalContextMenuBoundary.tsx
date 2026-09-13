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
      event.preventDefault()
      rightPointerId = event.pointerId
      rightSource = (event.target as Element | null)?.closest<HTMLElement>('[role="treeitem"][data-drop-id]') ?? null
    }

    const lostPointerCapture = (event: PointerEvent) => {
      // Losing native capture must not cancel an active DID right-drag. The
      // document-level bridge below keeps delivering the physical pointer
      // stream until pointerup/pointercancel.
      if (event.isTrusted && rightPointerId === event.pointerId && rightSource) event.stopPropagation()
    }

    const pointerMove = (event: PointerEvent) => {
      if (!event.isTrusted || rightPointerId !== event.pointerId || !rightSource) return
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
    document.addEventListener('lostpointercapture', lostPointerCapture, { capture: true })
    document.addEventListener('pointermove', pointerMove, { capture: true })
    document.addEventListener('pointerup', pointerUp, { capture: true })
    document.addEventListener('pointercancel', pointerCancel, { capture: true })
    document.addEventListener('contextmenu', preventContextMenu, { capture: true })
    return () => {
      document.removeEventListener('pointerdown', pointerDown, { capture: true })
      document.removeEventListener('lostpointercapture', lostPointerCapture, { capture: true })
      document.removeEventListener('pointermove', pointerMove, { capture: true })
      document.removeEventListener('pointerup', pointerUp, { capture: true })
      document.removeEventListener('pointercancel', pointerCancel, { capture: true })
      document.removeEventListener('contextmenu', preventContextMenu, { capture: true })
    }
  }, [])
  return <>{children}</>
}
