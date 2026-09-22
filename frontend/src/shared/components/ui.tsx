import {
  ActionIcon,
  Alert,
  Badge as MantineBadge,
  Box,
  Button as MantineButton,
  Menu as MantineMenu,
  Modal,
  NativeSelect,
  Notification,
  Progress as MantineProgress,
  Skeleton as MantineSkeleton,
  Stack,
  Text,
  TextInput,
  Tooltip as MantineTooltip,
  type ActionIconProps as MantineActionIconProps,
  type ButtonProps as MantineButtonProps,
  type ElementProps,
  type NativeSelectProps,
  type TextInputProps,
} from '@mantine/core'
import { AlertCircle } from 'lucide-react'
import { Children, isValidElement, useEffect, useRef, type CSSProperties, type HTMLAttributes, type KeyboardEvent as ReactKeyboardEvent, type ReactNode, type RefObject } from 'react'
import { useTranslation } from 'react-i18next'
import type { MessageKey } from '../../localization/catalog'

type ButtonProps = Omit<MantineButtonProps & ElementProps<'button'>, 'children' | 'color' | 'variant'> & { labelKey: MessageKey; disabledReasonKey?: MessageKey; variant?: 'primary'|'quiet'|'danger' }
export function Button({ labelKey, disabledReasonKey, variant = 'quiet', className, title, ...props }: ButtonProps) {
  const { t } = useTranslation()
  const disabledReason = props.disabled && disabledReasonKey ? t(disabledReasonKey) : undefined
  const resolvedTitle = disabledReason ?? title
  const button = (
    <MantineButton
      {...props}
      className={`button ${variant} ${className ?? ''}`}
      {...(resolvedTitle ? { title: resolvedTitle } : {})}
      variant={variant === 'primary' ? 'gradient' : variant === 'danger' ? 'outline' : 'default'}
      color={variant === 'danger' ? 'coral' : 'bunny'}
    >
      {t(labelKey)}
    </MantineButton>
  )
  return disabledReason ? <MantineTooltip label={disabledReason}><span>{button}</span></MantineTooltip> : button
}
type IconButtonProps = Omit<MantineActionIconProps & ElementProps<'button'>, 'children' | 'color' | 'variant'> & { labelKey: MessageKey; children: ReactNode }
export function IconButton({ labelKey, children, ...props }: IconButtonProps) {
  const { t } = useTranslation()
  return <ActionIcon {...props} className="icon-button" aria-label={t(labelKey)} title={t(labelKey)} variant="subtle" color="bunny">{children}</ActionIcon>
}
export function Input({ labelKey, ...props }: Omit<TextInputProps, 'label'> & { labelKey: MessageKey }) {
  const { t } = useTranslation()
  const id = props.id ?? `input-${labelKey}`
  return <TextInput {...props} id={id} className="field" label={t(labelKey)} />
}
export function Select({ labelKey, children, ...props }: Omit<NativeSelectProps, 'label'> & { labelKey: MessageKey; children: ReactNode }) {
  const { t } = useTranslation()
  const id = props.id ?? `select-${labelKey}`
  return <NativeSelect {...props} id={id} className="field" label={t(labelKey)}>{children}</NativeSelect>
}
export function Badge({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral'|'ok'|'warning'|'danger' }) {
  const colors = { neutral: 'gray', ok: 'mint', warning: 'amber', danger: 'coral' } as const
  return <MantineBadge className={`badge ${tone}`} color={colors[tone]} variant="light">{children}</MantineBadge>
}
export function Skeleton() {
  const { t } = useTranslation()
  return <Box className="skeleton" role="status" aria-label={t('common.loading')}><MantineSkeleton height={72} radius="lg" /></Box>
}
export function EmptyState({ messageKey }: { messageKey: MessageKey }) {
  const { t } = useTranslation()
  return <Alert className="state empty" color="bunny" variant="light">{t(messageKey)}</Alert>
}
export function ErrorState({ retry }: { retry?: () => void }) {
  const { t } = useTranslation()
  return <Alert className="state error" role="alert" color="coral" icon={<AlertCircle size={18} />}><Stack gap="sm"><Text>{t('errors.network.offline')}</Text>{retry && <Button labelKey="common.retry" onClick={retry} />}</Stack></Alert>
}
export function Progress({ value, labelKey }: { value: number | undefined; labelKey: MessageKey }) {
  const { t } = useTranslation()
  return <Stack className="progress" gap={6}><Text size="sm">{t(labelKey)}</Text><MantineProgress value={value ?? 100} animated={value === undefined} striped={value === undefined} aria-label={t(labelKey)} /></Stack>
}
export function Status({ children }: { children: ReactNode }) { return <Text component="span" role="status" className="status">{children}</Text> }
export function Tree({ children }: { children: ReactNode }) {
  const { t } = useTranslation(); const ref = useRef<HTMLDivElement>(null)
  useEffect(() => { const items = ref.current?.querySelectorAll<HTMLElement>('[role="treeitem"]'); const values = items ? [...items] : []; const first = values.at(0); if (first && !values.some((item) => item.tabIndex === 0)) first.tabIndex = 0 }, [children])
  function keyDown(event: ReactKeyboardEvent<HTMLDivElement>) { const items = [...(ref.current?.querySelectorAll<HTMLElement>('[role="treeitem"]') ?? [])].filter((item) => !item.closest('[hidden]')); const current = document.activeElement as HTMLElement; const index = items.indexOf(current); if (index < 0) return; if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); current.click(); return } let next = index; if (event.key === 'ArrowDown') next = Math.min(items.length - 1, index + 1); else if (event.key === 'ArrowUp') next = Math.max(0, index - 1); else if (event.key === 'Home') next = 0; else if (event.key === 'End') next = items.length - 1; else if (event.key === 'ArrowRight' && current.hasAttribute('aria-expanded')) { const group = current.querySelector<HTMLElement>(':scope > [role="group"]'); if (current.getAttribute('aria-expanded') === 'false') { current.setAttribute('aria-expanded', 'true'); if (group) group.hidden = false } else group?.querySelector<HTMLElement>('[role="treeitem"]')?.focus(); event.preventDefault(); return } else if (event.key === 'ArrowLeft') { const group = current.querySelector<HTMLElement>(':scope > [role="group"]'); if (current.getAttribute('aria-expanded') === 'true') { current.setAttribute('aria-expanded', 'false'); if (group) group.hidden = true } else current.parentElement?.closest<HTMLElement>('[role="treeitem"]')?.focus(); event.preventDefault(); return } else return; event.preventDefault(); items.forEach((item, itemIndex) => { item.tabIndex = itemIndex === next ? 0 : -1 }); items[next]?.focus() }
  return <div ref={ref} role="tree" aria-label={t('a11y.tree')} className="tree" onKeyDown={keyDown}>{children}</div>
}
export function TreeItem({ children, selected, level = 1, expandable = false, ...props }: HTMLAttributes<HTMLDivElement> & { selected?: boolean; level?: number; expandable?: boolean }) { return <div role="treeitem" aria-selected={selected} aria-level={level} aria-expanded={expandable ? true : undefined} tabIndex={selected ? 0 : -1} {...props}>{children}</div> }

export function Dialog(props: { open: boolean; titleKey: MessageKey; children: ReactNode; onClose: () => void; returnFocus?: RefObject<HTMLElement | null> }) {
  const { t } = useTranslation()
  return (
    <Modal
      opened={props.open}
      onClose={props.onClose}
      title={t(props.titleKey)}
      classNames={{ content: 'dialog' }}
      closeButtonProps={{ 'aria-label': t('common.close') }}
      onExitTransitionEnd={() => props.returnFocus?.current?.focus()}
    >
      {props.children}
    </Modal>
  )
}
export const AlertDialog = Dialog
export function Tooltip({ labelKey, children }: { labelKey: MessageKey; children: ReactNode }) {
  const { t } = useTranslation()
  return <MantineTooltip label={t(labelKey)}>{children}</MantineTooltip>
}
export function Toast({ children }: { children: ReactNode }) { return <Notification className="toast" role="status" aria-live="polite" withCloseButton={false} color="bunny">{children}</Notification> }
export function Menu({ labelKey, children, style, onClose }: { labelKey: MessageKey; children: ReactNode; style?: CSSProperties; onClose?: () => void }) {
  const { t } = useTranslation()
  const visibleChildren = labelKey === 'context.dropTitle'
    ? Children.toArray(children).filter((child) => isValidElement<{ disabled?: boolean }>(child) && child.props.disabled !== true)
    : children
  return (
    <MantineMenu opened {...(onClose ? { onClose } : {})} position="bottom-start" withinPortal shadow="md">
      <MantineMenu.Target>
        <span style={{ position: 'fixed', width: 1, height: 1, overflow: 'hidden', clipPath: 'inset(50%)', whiteSpace: 'nowrap', ...style }}>
          {t(labelKey)}
        </span>
      </MantineMenu.Target>
      <MantineMenu.Dropdown className="menu" aria-label={t(labelKey)}>{visibleChildren}</MantineMenu.Dropdown>
    </MantineMenu>
  )
}
export function MenuItem({ children, disabled, disabledReasonKey, onSelect }: { children: ReactNode; disabled?: boolean; disabledReasonKey?: MessageKey | undefined; onSelect: () => void }) {
  const { t } = useTranslation()
  const title = disabled && disabledReasonKey ? t(disabledReasonKey) : undefined
  return <MantineMenu.Item {...(disabled === undefined ? {} : { disabled })} {...(title ? { title } : {})} onClick={onSelect}>{children}</MantineMenu.Item>
}

const flagColors: Record<string, string> = { en: 'flag-en', fr: 'flag-fr', de: 'flag-de', es: 'flag-es' }
export function LocaleFlag({ locale, label }: { locale: string; label: string }) { return <span role="img" aria-label={label} className={`locale-flag ${flagColors[locale] ?? 'flag-runtime'}`}>{flagColors[locale] ? null : locale.toUpperCase()}</span> }
