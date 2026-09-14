import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { apiRequest } from '../../api/client'
import { useRoles } from '../../api/queries'
import type { CapabilityDecision, DashboardCapabilities, Role } from '../../api/types'
import type { DashboardContext } from '../../app/AppShell'
import { Badge, EmptyState, ErrorState, Skeleton } from '../../shared/components/ui'
import { capabilityPresentation, type CapabilityPresentation } from '../access/capabilityPresentation'
import { createValidatedAccessPlan, type AccessPlanNode } from '../access/planDraft'

type RoleAction =
  | { kind: 'create'; name: string }
  | { kind: 'rename'; role: Role; name: string }
  | { kind: 'delete'; role: Role }
  | { kind: 'reorder'; role: Role; position: number; direction: 'up' | 'down' }

function outcomeTone(value: string | undefined): 'ok' | 'warning' | 'danger' {
  return value === 'CAN' ? 'ok' : value === 'CANNOT' || value === 'ERROR' ? 'danger' : 'warning'
}

export function RolesScreen() {
  const { t } = useTranslation()
  const { me, guild, capabilities } = useOutletContext<DashboardContext>()
  const navigate = useNavigate()
  const query = useRoles(me.user.discord_user_id, guild.guild_id)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [action, setAction] = useState<RoleAction | null>(null)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)

  const roles = useMemo(() => [...(query.data?.roles ?? [])].sort((a, b) => b.position - a.position || a.name.localeCompare(b.name)), [query.data])
  const selected = roles.find((role) => role.id === selectedId) ?? null
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
    : isEveryone
      ? { outcome: 'CANNOT', causes: ['capability.hierarchy.default_role_mutation_forbidden'], remediations: [] }
      : manageDecision
  const managePresentation = capabilityPresentation({ isLoading: targetCapabilities.isLoading, isError: targetCapabilities.isError, decision: localTargetDecision })
  const reorderPresentation = capabilityPresentation({ isLoading: targetCapabilities.isLoading, isError: targetCapabilities.isError, decision: selected?.managed || isEveryone ? localTargetDecision : reorderDecision })

  function blockerText(presentation: CapabilityPresentation, role?: Role | null) {
    if (userCanWrite === 'CANNOT' || userCanPlan === 'CANNOT') return t('access.blocked.user')
    if (presentation.state === 'LOADING') return t('capability.loading')
    if (presentation.state === 'ERROR') return t('capability.queryError')
    if (presentation.reasonKey) return t(presentation.reasonKey, { role: role?.name ?? '' })
    return t('capability.cause.unclassified')
  }

  function canPrepare(kind: RoleAction['kind'], role?: Role | null) {
    if (userCanWrite !== 'CAN' || userCanPlan !== 'CAN') return false
    if (kind === 'create') return createBot === 'CAN'
    if (!role || role.managed || role.id === guild.guild_id) return false
    return (kind === 'reorder' ? reorderPresentation : managePresentation).state === 'CAN'
  }

  function capabilityTitle(presentation: CapabilityPresentation) {
    if (presentation.state === 'LOADING') return t('capability.loading')
    if (presentation.state === 'ERROR') return t('capability.errorTitle')
    if (presentation.state === 'CAN') return t('roles.botCan')
    if (presentation.state === 'CANNOT') return t('roles.botBlocked')
    return t('roles.botUnknown')
  }

  function capabilityBadge(presentation: CapabilityPresentation) {
    return t(`capability.badge.${presentation.state.toLowerCase()}`)
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
      const presentation = action.kind === 'reorder'
        ? reorderPresentation
        : action.kind === 'create'
          ? capabilityPresentation({ isLoading: false, isError: false, decision: capabilities?.bot_operations.CREATE_ROLE })
          : managePresentation
      setProblem(blockerText(presentation, role))
      return
    }
    setBusy(true)
    setProblem(null)
    try {
      let node: AccessPlanNode
      if (action.kind === 'create') {
        // Let Discord create the role at its safe default hierarchy position. A separate
        // reorder proposal can then move it only after the new role actually exists.
        // Guessing max(position)+1 here could place the requested role above the bot,
        // which Discord cannot apply and which the preflight would correctly reject.
        node = {
          logical_key: `ui.role.create.${crypto.randomUUID()}`,
          resource_type: 'ROLE',
          symbol: `role-${crypto.randomUUID()}`,
          properties: { name: action.name.trim(), permissions: '0' },
        }
      } else if (action.kind === 'rename') {
        node = {
          logical_key: `ui.role.rename.${action.role.id}`,
          resource_type: 'ROLE',
          discord_id: action.role.id,
          properties: { name: action.name.trim() },
        }
      } else if (action.kind === 'delete') {
        node = {
          logical_key: `ui.role.delete.${action.role.id}`,
          resource_type: 'ROLE',
          discord_id: action.role.id,
          presence: 'ABSENT',
        }
      } else {
        node = {
          logical_key: `ui.role.reorder.${action.role.id}`,
          resource_type: 'ROLE',
          discord_id: action.role.id,
          properties: { position: action.position },
        }
      }
      await createValidatedAccessPlan(guild.guild_id, [node])
      setAction(null)
      navigate(`/guild/${guild.guild_id}/plans`)
    } catch {
      setProblem(t('errors.generic', { requestId: 'unknown' }))
    } finally {
      setBusy(false)
    }
  }

  if (query.isLoading) return <Skeleton />
  if (query.isError) return <ErrorState retry={() => void query.refetch()} />
  if (!query.data || roles.length === 0) return <section className="access-page"><EmptyState messageKey="roles.empty" /></section>

  const selectedIndex = selected ? roles.findIndex((role) => role.id === selected.id) : -1
  const roleAbove = selectedIndex > 0 ? roles[selectedIndex - 1] : undefined
  const roleBelow = selectedIndex >= 0 && selectedIndex < roles.length - 1 ? roles[selectedIndex + 1] : undefined

  return (
    <section className="access-page roles-workbench">
      <header className="access-hero">
        <div><p className="access-eyebrow">{t('access.eyebrow')}</p><h1>{t('roles.title')}</h1><p>{t('roles.subtitle')}</p></div>
        <button type="button" className="button primary" disabled={!canPrepare('create')} title={!canPrepare('create') ? blockerText(capabilityPresentation({ isLoading: false, isError: false, decision: capabilities?.bot_operations.CREATE_ROLE })) : undefined} onClick={() => setAction({ kind: 'create', name: '' })}>{t('roles.create')}</button>
      </header>

      <div className="roles-layout">
        <article className="access-panel role-hierarchy-panel">
          <div className="access-panel-heading"><div><small>{t('roles.hierarchy')}</small><strong>{roles.length}</strong></div></div>
          <div className="role-hierarchy" role="listbox" aria-label={t('roles.hierarchy')}>
            {roles.map((role) => (
              <button key={role.id} type="button" role="option" aria-selected={selected?.id === role.id} className={`role-hierarchy-row ${selected?.id === role.id ? 'selected' : ''}`} onClick={() => { setSelectedId(role.id); setProblem(null) }}>
                <span className="role-position">{role.position}</span>
                <span className="role-dot" aria-hidden="true" />
                <span className="role-copy"><strong>{role.name}</strong><small>{t('roles.permissionsSummary', { count: role.known_flags.length })}</small></span>
                {role.managed && <Badge>{t('roles.managed')}</Badge>}
              </button>
            ))}
          </div>
        </article>

        <article className="access-panel role-detail-panel">
          {!selected ? <div className="access-empty"><span>◇</span><p>{t('roles.noSelection')}</p></div> : <>
            <div className="access-panel-heading"><div><small>{t('roles.details')}</small><strong>{selected.name}</strong></div><Badge tone={outcomeTone(managePresentation.state)}>{selected.managed ? t('roles.managed') : capabilityBadge(managePresentation)}</Badge></div>
            <div className="role-meta-grid">
              <div><span>{t('structure.inspector.discordId')}</span><strong>{selected.id}</strong></div>
              <div><span>{t('structure.inspector.position')}</span><strong>{selected.position}</strong></div>
              <div><span>{t('structure.inspector.freshness')}</span><strong>{selected.freshness}</strong></div>
              <div><span>{t('permissions.rawBitfield')}</span><strong>{selected.permissions}</strong></div>
            </div>
            {selected.managed && <p className="access-callout warning">{t('roles.managedHelp')}</p>}
            {selected.unknown_bits !== '0' && <p className="access-callout warning">{t('roles.unknownBits', { value: selected.unknown_bits })}</p>}
            <section className="permission-chip-section"><h2>{t('permissions.expertRoleFlags')}</h2><div className="permission-chip-cloud">{selected.known_flags.map((flag) => <span key={flag}>{flag}</span>)}</div></section>
            <section className="role-capability-card" aria-live="polite"><div><small>{t('roles.botCapability')}</small><strong>{capabilityTitle(managePresentation)}</strong></div>{managePresentation.state !== 'CAN' && managePresentation.state !== 'LOADING' && <p>{blockerText(managePresentation, selected)}</p>}{managePresentation.remediationKeys.map((key) => <p className="capability-remediation" key={key}>{t(key, { role: selected.name })}</p>)}{managePresentation.state === 'ERROR' && <button type="button" className="button quiet" onClick={() => void targetCapabilities.refetch()}>{t('capability.retry')}</button>}</section>
            <div className="role-action-grid">
              <button type="button" className="button quiet" disabled={!canPrepare('rename', selected)} title={!canPrepare('rename', selected) ? blockerText(managePresentation, selected) : undefined} onClick={() => setAction({ kind: 'rename', role: selected, name: selected.name })}>{t('roles.edit')}</button>
              <button type="button" className="button quiet" disabled={!roleAbove || !canPrepare('reorder', selected)} title={!canPrepare('reorder', selected) ? blockerText(reorderPresentation, selected) : undefined} onClick={() => roleAbove && setAction({ kind: 'reorder', role: selected, position: roleAbove.position, direction: 'up' })}>{t('roles.moveUp')}</button>
              <button type="button" className="button quiet" disabled={!roleBelow || !canPrepare('reorder', selected)} title={!canPrepare('reorder', selected) ? blockerText(reorderPresentation, selected) : undefined} onClick={() => roleBelow && setAction({ kind: 'reorder', role: selected, position: roleBelow.position, direction: 'down' })}>{t('roles.moveDown')}</button>
              <button type="button" className="button danger" disabled={!canPrepare('delete', selected)} title={!canPrepare('delete', selected) ? blockerText(managePresentation, selected) : undefined} onClick={() => setAction({ kind: 'delete', role: selected })}>{t('roles.delete')}</button>
            </div>
            {problem && <p className="access-callout danger" role="alert">{problem}</p>}
          </>}
        </article>
      </div>

      {action && <div className="dialog-backdrop"><div className="dialog access-impact-dialog" role="dialog" aria-modal="true" aria-labelledby="role-impact-title">
        <p className="access-eyebrow">{t('access.eyebrow')}</p><h2 id="role-impact-title">{t('roles.previewTitle')}</h2>
        {(action.kind === 'create' || action.kind === 'rename') && <label className="field"><span>{t('roles.name')}</span><input autoFocus value={action.name} maxLength={100} onChange={(event) => setAction(action.kind === 'create' ? { ...action, name: event.target.value } : { ...action, name: event.target.value })} /></label>}
        <div className="impact-summary"><span className="impact-icon">◎</span><div><strong>{action.kind === 'create' ? action.name || t('roles.create') : action.role.name}</strong><p>{actionDescription(action)}</p></div></div>
        {problem && <p className="access-callout danger" role="alert">{problem}</p>}
        <div className="button-row"><button type="button" className="button quiet" onClick={() => { setAction(null); setProblem(null) }}>{t('roles.cancelEdit')}</button><button type="button" className="button primary" disabled={busy || ((action.kind === 'create' || action.kind === 'rename') && action.name.trim().length === 0)} onClick={() => void prepare()}>{t('roles.prepare')}</button></div>
      </div></div>}
    </section>
  )
}
