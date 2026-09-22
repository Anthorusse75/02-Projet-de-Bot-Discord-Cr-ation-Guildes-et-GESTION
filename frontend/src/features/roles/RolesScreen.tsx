import { useMemo, useState } from 'react'
import { Accordion, Badge as MantineBadge, Button as MantineButton, Modal, TextInput, Tooltip } from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { ArrowDown, ArrowUp, Bot, Crown, Eye, MessageCircle, Pencil, Plus, Search, Settings2, Shield, ShieldCheck, Trash2, UsersRound, type LucideIcon } from 'lucide-react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { apiRequest } from '../../api/client'
import { useRoles } from '../../api/queries'
import type { CapabilityDecision, DashboardCapabilities, Role } from '../../api/types'
import type { DashboardContext } from '../../app/AppShell'
import { EmptyState, ErrorState, Skeleton } from '../../shared/components/ui'
import { capabilityPresentation, type CapabilityPresentation } from '../access/capabilityPresentation'
import { createValidatedAccessPlan, type AccessPlanNode } from '../access/planDraft'

type RoleAction =
  | { kind: 'create'; name: string }
  | { kind: 'rename'; role: Role; name: string }
  | { kind: 'delete'; role: Role }
  | { kind: 'reorder'; role: Role; position: number; direction: 'up' | 'down' }
type RoleGroupKey = 'administration' | 'moderation' | 'community' | 'automation'
type RoleFilter = 'all' | RoleGroupKey
type RoleGroup = { key: RoleGroupKey; icon: LucideIcon; roles: Role[] }

const moderationFlags = new Set(['BAN_MEMBERS', 'KICK_MEMBERS', 'MODERATE_MEMBERS', 'MANAGE_MESSAGES', 'MANAGE_THREADS'])
const administrationFlags = new Set(['ADMINISTRATOR', 'MANAGE_GUILD', 'MANAGE_ROLES', 'MANAGE_CHANNELS'])

function hasAny(role: Role, flags: Set<string>) { return role.known_flags.some((flag) => flags.has(flag)) }
function groupForRole(role: Role): RoleGroupKey {
  const name = role.name.toLocaleLowerCase()
  if (role.managed || name.includes('bot') || name.includes('integration')) return 'automation'
  if (hasAny(role, administrationFlags) || /admin|owner|fondateur|founder/.test(name)) return 'administration'
  if (hasAny(role, moderationFlags) || /mod|staff|support/.test(name)) return 'moderation'
  return 'community'
}
function displayRoleName(role: Role, bunnyName: string) { return /^did bot$/i.test(role.name.trim()) ? bunnyName : role.name }
function roleSummaryKey(role: Role) {
  if (role.managed) return 'roles.summary.managed'
  if (role.known_flags.includes('ADMINISTRATOR')) return 'roles.summary.administration'
  if (hasAny(role, moderationFlags)) return 'roles.summary.moderation'
  if (role.known_flags.includes('MANAGE_ROLES') || role.known_flags.includes('MANAGE_CHANNELS')) return 'roles.summary.organization'
  if (role.known_flags.includes('SEND_MESSAGES') || role.known_flags.includes('SEND_MESSAGES_IN_THREADS')) return 'roles.summary.participation'
  if (role.known_flags.includes('VIEW_CHANNEL')) return 'roles.summary.visibility'
  return 'roles.summary.identity'
}
function roleCapabilities(role: Role): Array<{ key: string; icon: LucideIcon; enabled: boolean }> {
  const administrator = role.known_flags.includes('ADMINISTRATOR')
  return [
    { key: 'visibility', icon: Eye, enabled: administrator || role.known_flags.includes('VIEW_CHANNEL') },
    { key: 'publication', icon: MessageCircle, enabled: administrator || role.known_flags.some((flag) => ['SEND_MESSAGES', 'SEND_MESSAGES_IN_THREADS', 'SPEAK'].includes(flag)) },
    { key: 'moderation', icon: Shield, enabled: administrator || hasAny(role, moderationFlags) },
    { key: 'administration', icon: Settings2, enabled: administrator || hasAny(role, administrationFlags) },
  ]
}

export function RolesScreen() {
  const { t } = useTranslation()
  const { me, guild, capabilities } = useOutletContext<DashboardContext>()
  const navigate = useNavigate()
  const query = useRoles(me.user.discord_user_id, guild.guild_id)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [activeFilter, setActiveFilter] = useState<RoleFilter>('all')
  const [search, setSearch] = useState('')
  const [action, setAction] = useState<RoleAction | null>(null)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)

  const roles = useMemo(() => [...(query.data?.roles ?? [])].sort((a, b) => b.position - a.position || a.name.localeCompare(b.name)), [query.data])
  const selected = roles.find((role) => role.id === selectedId) ?? roles[0] ?? null
  const groups = useMemo<RoleGroup[]>(() => {
    const keys: RoleGroupKey[] = ['administration', 'moderation', 'community', 'automation']
    const icons: Record<RoleGroupKey, LucideIcon> = { administration: Crown, moderation: ShieldCheck, community: UsersRound, automation: Bot }
    const needle = search.trim().toLocaleLowerCase()
    return keys.map((key) => ({ key, icon: icons[key], roles: roles.filter((role) => groupForRole(role) === key && (!needle || displayRoleName(role, t('roles.bunnyRole')).toLocaleLowerCase().includes(needle))) })).filter((group) => (activeFilter === 'all' || group.key === activeFilter) && group.roles.length > 0)
  }, [activeFilter, roles, search, t])

  const targetCapabilities = useQuery({
    enabled: Boolean(selected),
    queryKey: ['did', me.user.discord_user_id, guild.guild_id, 'dashboard-capabilities', 'role', selected?.id ?? 'none'],
    queryFn: () => apiRequest<DashboardCapabilities>(`/api/v1/guilds/${guild.guild_id}/dashboard-capabilities?target_role_id=${encodeURIComponent(selected?.id ?? '')}`),
  })
  const userCanWrite = capabilities?.user_capabilities['roles.write']?.outcome ?? 'UNKNOWN'
  const userCanPlan = capabilities?.user_capabilities['plans.create']?.outcome ?? 'UNKNOWN'
  const createBot = capabilities?.bot_operations.CREATE_ROLE?.outcome ?? 'UNKNOWN'
  const manageDecision = targetCapabilities.data?.bot_operations.MANAGE_ROLE
  const reorderDecision = targetCapabilities.data?.bot_operations.REORDER_ROLES
  const isEveryone = selected?.id === guild.guild_id
  const localTargetDecision: CapabilityDecision | undefined = selected?.managed
    ? { outcome: 'CANNOT', causes: ['capability.hierarchy.target_managed'], remediations: [] }
    : isEveryone ? { outcome: 'CANNOT', causes: ['capability.hierarchy.default_role_mutation_forbidden'], remediations: [] } : manageDecision
  const managePresentation = capabilityPresentation({ isLoading: targetCapabilities.isLoading, isError: targetCapabilities.isError, decision: localTargetDecision })
  const reorderPresentation = capabilityPresentation({ isLoading: targetCapabilities.isLoading, isError: targetCapabilities.isError, decision: selected?.managed || isEveryone ? localTargetDecision : reorderDecision })

  function blockerText(presentation: CapabilityPresentation, role?: Role | null) {
    if (userCanWrite === 'CANNOT' || userCanPlan === 'CANNOT') return t('access.blocked.user')
    if (presentation.state === 'LOADING') return t('capability.loading')
    if (presentation.state === 'ERROR') return t('capability.queryError')
    if (presentation.reasonKey) return t(presentation.reasonKey, { role: role ? displayRoleName(role, t('roles.bunnyRole')) : '' })
    return t('capability.cause.unclassified')
  }
  function canPrepare(kind: RoleAction['kind'], role?: Role | null) {
    if (userCanWrite !== 'CAN' || userCanPlan !== 'CAN') return false
    if (kind === 'create') return createBot === 'CAN'
    if (!role || role.managed || role.id === guild.guild_id) return false
    return (kind === 'reorder' ? reorderPresentation : managePresentation).state === 'CAN'
  }
  function actionDescription(value: RoleAction) {
    if (value.kind === 'create') return t('roles.createImpact')
    if (value.kind === 'rename') return t('roles.renameImpact')
    if (value.kind === 'delete') return t('roles.deleteImpact')
    return t('roles.reorderImpact')
  }
  async function prepare() {
    if (!action) return
    const role = action.kind === 'create' ? null : action.role
    if (!canPrepare(action.kind, role)) {
      const presentation = action.kind === 'reorder' ? reorderPresentation : action.kind === 'create' ? capabilityPresentation({ isLoading: false, isError: false, decision: capabilities?.bot_operations.CREATE_ROLE }) : managePresentation
      setProblem(blockerText(presentation, role)); return
    }
    setBusy(true); setProblem(null)
    try {
      let node: AccessPlanNode
      if (action.kind === 'create') node = { logical_key: `ui.role.create.${crypto.randomUUID()}`, resource_type: 'ROLE', symbol: `role-${crypto.randomUUID()}`, properties: { name: action.name.trim(), permissions: '0' } }
      else if (action.kind === 'rename') node = { logical_key: `ui.role.rename.${action.role.id}`, resource_type: 'ROLE', discord_id: action.role.id, properties: { name: action.name.trim() } }
      else if (action.kind === 'delete') node = { logical_key: `ui.role.delete.${action.role.id}`, resource_type: 'ROLE', discord_id: action.role.id, presence: 'ABSENT' }
      else node = { logical_key: `ui.role.reorder.${action.role.id}`, resource_type: 'ROLE', discord_id: action.role.id, properties: { position: action.position } }
      await createValidatedAccessPlan(guild.guild_id, [node]); setAction(null); navigate(`/guild/${guild.guild_id}/plans`)
    } catch { setProblem(t('errors.generic', { requestId: 'unknown' })) } finally { setBusy(false) }
  }
  function closeAction() { setAction(null); setProblem(null) }

  if (query.isLoading) return <Skeleton />
  if (query.isError) return <ErrorState retry={() => void query.refetch()} />
  if (!query.data || roles.length === 0) return <section className="access-page"><EmptyState messageKey="roles.empty" /></section>

  const selectedIndex = selected ? roles.findIndex((role) => role.id === selected.id) : -1
  const roleAbove = selectedIndex > 0 ? roles[selectedIndex - 1] : undefined
  const roleBelow = selectedIndex >= 0 && selectedIndex < roles.length - 1 ? roles[selectedIndex + 1] : undefined
  const selectedGroup = selected ? groupForRole(selected) : 'community'
  const SelectedIcon = selectedGroup === 'administration' ? Crown : selectedGroup === 'moderation' ? ShieldCheck : selectedGroup === 'automation' ? Bot : UsersRound

  return <section className="access-page roles-workbench bunny-roles-page">
    <header className="roles-page-header">
      <div className="roles-page-heading"><span className="roles-page-icon"><UsersRound size={27} /></span><div><p className="access-eyebrow">{t('roles.eyebrow')}</p><h1>{t('roles.title')}</h1><p>{t('roles.subtitle')}</p></div></div>
      <Tooltip disabled={canPrepare('create')} label={blockerText(capabilityPresentation({ isLoading: false, isError: false, decision: capabilities?.bot_operations.CREATE_ROLE }))}><MantineButton leftSection={<Plus size={18} />} size="md" radius="md" disabled={!canPrepare('create')} onClick={() => setAction({ kind: 'create', name: '' })}>{t('roles.create')}</MantineButton></Tooltip>
    </header>
    <div className="roles-toolbar">
      <div className="roles-filters" role="group" aria-label={t('roles.filters')}>{(['all', 'administration', 'moderation', 'community', 'automation'] as RoleFilter[]).map((filter) => { const count = filter === 'all' ? roles.length : roles.filter((role) => groupForRole(role) === filter).length; return <button key={filter} type="button" className={activeFilter === filter ? 'active' : ''} onClick={() => setActiveFilter(filter)}>{t(`roles.group.${filter}`)} <span>{count}</span></button> })}</div>
      <TextInput className="roles-search" value={search} onChange={(event) => setSearch(event.currentTarget.value)} placeholder={t('roles.search')} aria-label={t('roles.search')} leftSection={<Search size={16} />} />
    </div>
    <div className="roles-canonical-layout">
      <div className="roles-groups" role="listbox" aria-label={t('roles.hierarchy')}>
        {groups.length === 0 && <div className="roles-no-results"><Search size={24} /><p>{t('common.noResults')}</p></div>}
        {groups.map((group) => { const GroupIcon = group.icon; return <section className={`roles-group roles-group-${group.key}`} key={group.key}>
          <header><span><GroupIcon size={19} /></span><div><h2>{t(`roles.group.${group.key}`)}</h2><p>{t(`roles.group.${group.key}.copy`)}</p></div><MantineBadge variant="light" color="gray">{t('roles.count', { count: group.roles.length })}</MantineBadge></header>
          <div className="role-card-grid">{group.roles.map((role) => { const roleName = displayRoleName(role, t('roles.bunnyRole')); return <button key={role.id} type="button" role="option" aria-selected={selected?.id === role.id} className="role-card" onClick={() => { setSelectedId(role.id); setProblem(null) }}><span className="role-card-icon"><GroupIcon size={21} /></span><span className="role-card-copy"><strong>{roleName}</strong><small>{t(roleSummaryKey(role))}</small></span><span className="role-card-meta">{role.managed ? t('roles.managed') : t('roles.permissionsShort', { count: role.known_flags.length })}</span></button> })}</div>
        </section> })}
      </div>
      <aside className={`role-detail-canonical role-detail-${selectedGroup}`} aria-label={t('roles.details')}>{selected && <>
        <header className="role-detail-identity"><span className="role-detail-icon"><SelectedIcon size={30} /></span><div><h2>{displayRoleName(selected, t('roles.bunnyRole'))}</h2><p>{t(roleSummaryKey(selected))}</p></div>{(selected.managed || isEveryone) && <MantineBadge color="coral" variant="light">{selected.managed ? t('roles.managed') : t('roles.system')}</MantineBadge>}</header>
        {canPrepare('rename', selected) && <MantineButton className="role-primary-action" variant="light" leftSection={<Pencil size={17} />} onClick={() => setAction({ kind: 'rename', role: selected, name: displayRoleName(selected, t('roles.bunnyRole')) })}>{t('roles.edit')}</MantineButton>}
        <div className="role-human-capabilities">{roleCapabilities(selected).map(({ key, icon: CapabilityIcon, enabled }) => <article key={key} className={enabled ? 'enabled' : 'quiet'}><span><CapabilityIcon size={19} /></span><div><strong>{t(`roles.capability.${key}`)}</strong><p>{t(`roles.capability.${key}.copy`)}</p></div><MantineBadge color={enabled ? 'mint' : 'gray'} variant="light">{t(enabled ? 'roles.status.enabled' : 'roles.status.notGranted')}</MantineBadge></article>)}</div>
        {managePresentation.state !== 'CAN' && <section className={`role-capability-notice ${managePresentation.state.toLowerCase()}`} aria-live="polite"><strong>{t(`roles.capabilityState.${managePresentation.state.toLowerCase()}`)}</strong><p>{blockerText(managePresentation, selected)}</p>{managePresentation.remediationKeys.map((key) => <p className="capability-remediation" key={key}>{t(key, { role: displayRoleName(selected, t('roles.bunnyRole')) })}</p>)}{managePresentation.state === 'ERROR' && <MantineButton size="xs" variant="light" onClick={() => void targetCapabilities.refetch()}>{t('capability.retry')}</MantineButton>}</section>}
        <Accordion className="role-discord-details" variant="contained" radius="md"><Accordion.Item value="discord-details"><Accordion.Control icon={<Settings2 size={18} />}>{t('roles.discordDetails')}</Accordion.Control><Accordion.Panel><div className="role-technical-grid"><div><span>{t('structure.inspector.discordId')}</span><code>{selected.id}</code></div><div><span>{t('structure.inspector.position')}</span><code>{selected.position}</code></div><div><span>{t('structure.inspector.freshness')}</span><code>{selected.freshness}</code></div><div><span>{t('permissions.rawBitfield')}</span><code>{selected.permissions}</code></div></div>{selected.unknown_bits !== '0' && <p className="access-callout warning">{t('roles.unknownBits', { value: selected.unknown_bits })}</p>}<div className="permission-chip-cloud">{selected.known_flags.map((flag) => <span key={flag}>{flag}</span>)}</div></Accordion.Panel></Accordion.Item></Accordion>
        {((roleAbove && canPrepare('reorder', selected)) || (roleBelow && canPrepare('reorder', selected)) || canPrepare('delete', selected)) && <div className="role-secondary-actions">{roleAbove && canPrepare('reorder', selected) && <MantineButton variant="subtle" color="gray" leftSection={<ArrowUp size={16} />} onClick={() => setAction({ kind: 'reorder', role: selected, position: roleAbove.position, direction: 'up' })}>{t('roles.moveUp')}</MantineButton>}{roleBelow && canPrepare('reorder', selected) && <MantineButton variant="subtle" color="gray" leftSection={<ArrowDown size={16} />} onClick={() => setAction({ kind: 'reorder', role: selected, position: roleBelow.position, direction: 'down' })}>{t('roles.moveDown')}</MantineButton>}{canPrepare('delete', selected) && <MantineButton variant="outline" color="coral" leftSection={<Trash2 size={16} />} onClick={() => setAction({ kind: 'delete', role: selected })}>{t('roles.delete')}</MantineButton>}</div>}
        {problem && <p className="access-callout danger" role="alert">{problem}</p>}
      </>}</aside>
    </div>
    <Modal opened={Boolean(action)} onClose={closeAction} title={t('roles.previewTitle')} centered classNames={{ content: 'role-action-modal' }}>{action && <>{(action.kind === 'create' || action.kind === 'rename') && <TextInput autoFocus label={t('roles.name')} value={action.name} maxLength={100} onChange={(event) => setAction({ ...action, name: event.currentTarget.value })}/>}<div className="impact-summary"><span className="impact-icon"><ShieldCheck size={18} /></span><div><strong>{action.kind === 'create' ? action.name || t('roles.create') : displayRoleName(action.role, t('roles.bunnyRole'))}</strong><p>{actionDescription(action)}</p></div></div>{problem && <p className="access-callout danger" role="alert">{problem}</p>}<div className="button-row"><MantineButton variant="default" onClick={closeAction}>{t('roles.cancelEdit')}</MantineButton><MantineButton loading={busy} disabled={(action.kind === 'create' || action.kind === 'rename') && action.name.trim().length === 0} onClick={() => void prepare()}>{t('roles.prepare')}</MantineButton></div></>}</Modal>
  </section>
}
