import type { ResourceRef } from './actions'

export const DRAG_THRESHOLDS = { mouse: 6, pen: 8, touch: 12 } as const
type PointerKind = keyof typeof DRAG_THRESHOLDS
export type GestureResult = { kind: 'context' | 'left-drag' | 'right-drag' | 'cancel'; source: ResourceRef; x: number; y: number }
type Active = { id: number; button: 0 | 2; pointerType: PointerKind; source: ResourceRef; startX: number; startY: number; x: number; y: number; dragging: boolean }

export class PointerGestureManager {
  private active: Active | null = null
  start(event: Pick<PointerEvent, 'pointerId'|'button'|'pointerType'|'clientX'|'clientY'>, source: ResourceRef) {
    if (event.button !== 0 && event.button !== 2) return
    const pointerType = event.pointerType in DRAG_THRESHOLDS ? event.pointerType as PointerKind : 'mouse'
    this.active = { id: event.pointerId, button: event.button, pointerType, source, startX: event.clientX, startY: event.clientY, x: event.clientX, y: event.clientY, dragging: false }
  }
  move(event: Pick<PointerEvent, 'pointerId'|'clientX'|'clientY'>): boolean {
    if (!this.active || event.pointerId !== this.active.id) return false
    this.active.x = event.clientX; this.active.y = event.clientY
    const distance = Math.hypot(event.clientX - this.active.startX, event.clientY - this.active.startY)
    if (distance >= DRAG_THRESHOLDS[this.active.pointerType]) this.active.dragging = true
    return this.active.dragging
  }
  finish(event: Pick<PointerEvent, 'pointerId'|'clientX'|'clientY'>): GestureResult | null {
    if (!this.active || event.pointerId !== this.active.id) return null
    const active = this.active; this.active = null
    const kind = active.dragging ? (active.button === 2 ? 'right-drag' : 'left-drag') : (active.button === 2 ? 'context' : 'cancel')
    return { kind, source: active.source, x: event.clientX, y: event.clientY }
  }
  cancel(): GestureResult | null {
    if (!this.active) return null
    const value = this.active; this.active = null
    return { kind: 'cancel', source: value.source, x: value.x, y: value.y }
  }
}
