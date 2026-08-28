import { useEffect, useId, useRef, type ButtonHTMLAttributes, type HTMLAttributes, type InputHTMLAttributes, type KeyboardEvent as ReactKeyboardEvent, type ReactNode, type RefObject, type SelectHTMLAttributes } from 'react'
import { useTranslation } from 'react-i18next'
import type { MessageKey } from '../../localization/catalog'

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & { labelKey: MessageKey; disabledReasonKey?: MessageKey; variant?: 'primary'|'quiet'|'danger' }
export function Button({ labelKey, disabledReasonKey, variant = 'quiet', ...props }: ButtonProps) {
  const { t } = useTranslation()
  return <button {...props} className={`button ${variant} ${props.className ?? ''}`} title={props.disabled && disabledReasonKey ? t(disabledReasonKey) : props.title}>{t(labelKey)}</button>
}
export function IconButton({ labelKey, children, ...props }: ButtonProps & { children: ReactNode }) {
  const { t } = useTranslation(); return <button {...props} className="icon-button" aria-label={t(labelKey)} title={t(labelKey)}>{children}</button>
}
export function Input({ labelKey, ...props }: InputHTMLAttributes<HTMLInputElement> & { labelKey: MessageKey }) {
  const { t } = useTranslation(); const id = props.id ?? `input-${labelKey}`
  return <label className="field" htmlFor={id}><span>{t(labelKey)}</span><input {...props} id={id} /></label>
}
export function Select({ labelKey, children, ...props }: SelectHTMLAttributes<HTMLSelectElement> & { labelKey: MessageKey; children: ReactNode }) {
  const { t } = useTranslation(); const id = props.id ?? `select-${labelKey}`
  return <label className="field" htmlFor={id}><span>{t(labelKey)}</span><select {...props} id={id}>{children}</select></label>
}
export function Badge({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral'|'ok'|'warning'|'danger' }) { return <span className={`badge ${tone}`}>{children}</span> }
export function Skeleton() { const { t } = useTranslation(); return <div className="skeleton" role="status"><span>{t('common.loading')}</span></div> }
export function EmptyState({ messageKey }: { messageKey: MessageKey }) { const { t } = useTranslation(); return <div className="state empty">{t(messageKey)}</div> }
export function ErrorState({ retry }: { retry?: () => void }) { const { t } = useTranslation(); return <div className="state error" role="alert"><p>{t('errors.network.offline')}</p>{retry && <Button labelKey="common.retry" onClick={retry} />}</div> }
export function Progress({ value, labelKey }: { value: number | undefined; labelKey: MessageKey }) { const { t } = useTranslation(); return <label className="progress"><span>{t(labelKey)}</span><progress max={100} {...(value === undefined ? {} : { value })}>{value === undefined ? t('plans.progress.indeterminate') : `${value}%`}</progress></label> }
export function Status({ children }: { children: ReactNode }) { return <span role="status" className="status">{children}</span> }
export function Tabs({ children, ...props }: HTMLAttributes<HTMLDivElement>) { return <div role="tablist" {...props}>{children}</div> }
export function Tree({ children }: { children: ReactNode }) {
  const { t } = useTranslation(); const ref = useRef<HTMLDivElement>(null)
  useEffect(() => { const items = ref.current?.querySelectorAll<HTMLElement>('[role="treeitem"]'); const values = items ? [...items] : []; const first = values.at(0); if (first && !values.some((item) => item.tabIndex === 0)) first.tabIndex = 0 }, [children])
  function keyDown(event: ReactKeyboardEvent<HTMLDivElement>) { const items = [...(ref.current?.querySelectorAll<HTMLElement>('[role="treeitem"]') ?? [])].filter((item) => !item.closest('[hidden]')); const current = document.activeElement as HTMLElement; const index = items.indexOf(current); if (index < 0) return; if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); current.click(); return } let next = index; if (event.key === 'ArrowDown') next = Math.min(items.length - 1, index + 1); else if (event.key === 'ArrowUp') next = Math.max(0, index - 1); else if (event.key === 'Home') next = 0; else if (event.key === 'End') next = items.length - 1; else if (event.key === 'ArrowRight' && current.hasAttribute('aria-expanded')) { const group = current.querySelector<HTMLElement>(':scope > [role="group"]'); if (current.getAttribute('aria-expanded') === 'false') { current.setAttribute('aria-expanded', 'true'); if (group) group.hidden = false } else group?.querySelector<HTMLElement>('[role="treeitem"]')?.focus(); event.preventDefault(); return } else if (event.key === 'ArrowLeft') { const group = current.querySelector<HTMLElement>(':scope > [role="group"]'); if (current.getAttribute('aria-expanded') === 'true') { current.setAttribute('aria-expanded', 'false'); if (group) group.hidden = true } else current.parentElement?.closest<HTMLElement>('[role="treeitem"]')?.focus(); event.preventDefault(); return } else return; event.preventDefault(); items.forEach((item, itemIndex) => { item.tabIndex = itemIndex === next ? 0 : -1 }); items[next]?.focus() }
  return <div ref={ref} role="tree" aria-label={t('a11y.tree')} className="tree" onKeyDown={keyDown}>{children}</div>
}
export function TreeItem({ children, selected, level = 1, expandable = false, ...props }: HTMLAttributes<HTMLDivElement> & { selected?: boolean; level?: number; expandable?: boolean }) { return <div role="treeitem" aria-selected={selected} aria-level={level} aria-expanded={expandable ? true : undefined} tabIndex={selected ? 0 : -1} {...props}>{children}</div> }

export function Dialog({ open, titleKey, children, onClose, returnFocus }: { open: boolean; titleKey: MessageKey; children: ReactNode; onClose: () => void; returnFocus?: RefObject<HTMLElement | null> }) {
  const { t } = useTranslation(); const ref = useRef<HTMLDivElement>(null); const titleId = useId(); const onCloseRef = useRef(onClose); onCloseRef.current = onClose
  useEffect(() => {
    if (!open) return
    const previous = document.activeElement as HTMLElement | null
    ref.current?.querySelector<HTMLElement>('button,input,select,[tabindex="0"]')?.focus()
    const key = (event: KeyboardEvent) => { if (event.key === 'Escape') { event.preventDefault(); onCloseRef.current(); return } if (event.key !== 'Tab') return; const focusable = [...(ref.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),a[href],[tabindex="0"]') ?? [])]; const first = focusable.at(0); const last = focusable.at(-1); if (!first || !last) return; if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() } }
    document.addEventListener('keydown', key)
    return () => { document.removeEventListener('keydown', key); (returnFocus?.current ?? previous)?.focus() }
  }, [open])
  if (!open) return null
  return <div className="dialog-backdrop"><div ref={ref} role="dialog" aria-modal="true" aria-labelledby={titleId} className="dialog"><h2 id={titleId}>{t(titleKey)}</h2>{children}<Button labelKey="common.close" onClick={onClose} /></div></div>
}
export const AlertDialog = Dialog
export function Tooltip({ labelKey, children }: { labelKey: MessageKey; children: ReactNode }) { const { t } = useTranslation(); return <span title={t(labelKey)}>{children}</span> }
export function Toast({ children }: { children: ReactNode }) { return <div className="toast" role="status" aria-live="polite">{children}</div> }
export function Menu({ labelKey, children, style, onClose }: { labelKey: MessageKey; children: ReactNode; style?: React.CSSProperties; onClose?: () => void }) { const { t } = useTranslation(); const ref = useRef<HTMLDivElement>(null); useEffect(() => { const previous = document.activeElement as HTMLElement | null; ref.current?.querySelector<HTMLElement>('[role="menuitem"]:not(:disabled)')?.focus(); return () => previous?.focus() }, []); function keyDown(event: ReactKeyboardEvent) { const items = [...(ref.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)') ?? [])]; const index = items.indexOf(document.activeElement as HTMLButtonElement); if (event.key === 'Escape') { event.preventDefault(); onClose?.(); return } if (!items.length) return; let next: number; if (event.key === 'ArrowDown') next = (index + 1) % items.length; else if (event.key === 'ArrowUp') next = (index - 1 + items.length) % items.length; else if (event.key === 'Home') next = 0; else if (event.key === 'End') next = items.length - 1; else return; event.preventDefault(); items[next]?.focus() } return <div ref={ref} role="menu" aria-label={t(labelKey)} className="menu" style={style} onKeyDown={keyDown}>{children}</div> }
export function MenuItem({ children, disabled, disabledReasonKey, onSelect }: { children: ReactNode; disabled?: boolean; disabledReasonKey?: MessageKey | undefined; onSelect: () => void }) { const { t } = useTranslation(); return <button type="button" role="menuitem" disabled={disabled} title={disabled && disabledReasonKey ? t(disabledReasonKey) : undefined} onClick={onSelect}>{children}</button> }

const flagColors: Record<string, string> = { en: 'flag-en', fr: 'flag-fr', de: 'flag-de', es: 'flag-es' }
export function LocaleFlag({ locale, label }: { locale: string; label: string }) { return <span role="img" aria-label={label} className={`locale-flag ${flagColors[locale] ?? 'flag-runtime'}`}>{flagColors[locale] ? null : locale.toUpperCase()}</span> }
