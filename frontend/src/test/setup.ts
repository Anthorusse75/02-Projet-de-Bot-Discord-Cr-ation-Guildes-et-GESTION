import '@testing-library/jest-dom/vitest'

if (!HTMLElement.prototype.setPointerCapture) HTMLElement.prototype.setPointerCapture = () => undefined
if (!HTMLElement.prototype.releasePointerCapture) HTMLElement.prototype.releasePointerCapture = () => undefined
if (!HTMLElement.prototype.hasPointerCapture) HTMLElement.prototype.hasPointerCapture = () => true
if (!window.PointerEvent) {
  class TestPointerEvent extends MouseEvent {
    pointerId: number
    pointerType: string
    constructor(type: string, values: PointerEventInit = {}) {
      super(type, values); this.pointerId = values.pointerId ?? 0; this.pointerType = values.pointerType ?? 'mouse'
    }
  }
  window.PointerEvent = TestPointerEvent as typeof PointerEvent
}
