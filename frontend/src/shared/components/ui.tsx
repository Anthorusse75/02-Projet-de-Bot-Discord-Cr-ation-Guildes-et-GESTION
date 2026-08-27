import { useEffect, useRef, type ButtonHTMLAttributes, type HTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from 'react'
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
export function Progress({ value, labelKey }: { value: number; labelKey: MessageKey }) { const { t } = useTranslation(); return <label className="progress"><span>{t(labelKey)}</span><progress max={100} value={value}>{value}%</progress></label> }
export function Status({ children }: { children: ReactNode }) { return <span role="status" className="status">{children}</span> }
export function Tabs({ children, ...props }: HTMLAttributes<HTMLDivElement>) { return <div role="tablist" {...props}>{children}</div> }
export function Tree({ children }: { children: ReactNode }) { const { t } = useTranslation(); return <div role="tree" aria-label={t('a11y.tree')} className="tree">{children}</div> }
export function TreeItem({ children, selected, level = 1, ...props }: HTMLAttributes<HTMLDivElement> & { selected?: boolean; level?: number }) { return <div role="treeitem" aria-selected={selected} aria-level={level} tabIndex={selected ? 0 : -1} {...props}>{children}</div> }

export function Dialog({ open, titleKey, children, onClose }: { open: boolean; titleKey: MessageKey; children: ReactNode; onClose: () => void }) {
  const { t } = useTranslation(); const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const previous = document.activeElement as HTMLElement | null
    ref.current?.querySelector<HTMLElement>('button,input,select,[tabindex="0"]')?.focus()
    const key = (event: KeyboardEvent) => { if (event.key === 'Escape') { event.preventDefault(); onClose() } }
    document.addEventListener('keydown', key)
    return () => { document.removeEventListener('keydown', key); previous?.focus() }
  }, [open, onClose])
  if (!open) return null
  return <div className="dialog-backdrop"><div ref={ref} role="dialog" aria-modal="true" aria-labelledby="dialog-title" className="dialog"><h2 id="dialog-title">{t(titleKey)}</h2>{children}<Button labelKey="common.close" onClick={onClose} /></div></div>
}
export const AlertDialog = Dialog
export function Tooltip({ labelKey, children }: { labelKey: MessageKey; children: ReactNode }) { const { t } = useTranslation(); return <span title={t(labelKey)}>{children}</span> }
export function Toast({ children }: { children: ReactNode }) { return <div className="toast" role="status" aria-live="polite">{children}</div> }
export function Menu({ labelKey, children, style }: { labelKey: MessageKey; children: ReactNode; style?: React.CSSProperties }) { const { t } = useTranslation(); return <div role="menu" aria-label={t(labelKey)} className="menu" style={style}>{children}</div> }
export function MenuItem({ children, disabled, onSelect }: { children: ReactNode; disabled?: boolean; onSelect: () => void }) { return <button type="button" role="menuitem" disabled={disabled} onClick={onSelect}>{children}</button> }

const flagColors = { en: 'flag-en', fr: 'flag-fr', de: 'flag-de', es: 'flag-es' } as const
export function LocaleFlag({ locale, labelKey }: { locale: keyof typeof flagColors; labelKey: MessageKey }) { const { t } = useTranslation(); return <span role="img" aria-label={t(labelKey)} className={`locale-flag ${flagColors[locale]}`} /> }
