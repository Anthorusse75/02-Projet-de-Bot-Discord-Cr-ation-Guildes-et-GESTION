import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { apiRequest } from '../../api/client'
import { useRoles } from '../../api/queries'
import type { DashboardCapabilities, Role } from '../../api/types'
import type { DashboardContext } from '../../app/AppShell'
import { Badge, EmptyState, ErrorState, Skeleton } from '../../shared/components/ui'
import { createValidatedAccessPlan, type AccessPlanNode } from '../access/planDraft'

type RoleAction =
  | { kind: 'create'; name: string }
  | { kind: 'rename'; role: Role; name: string }
  | { kind: 'delete'; role: Role }
  | { kind: 'reorder'; role: Role; position: number; direction: 'up' | 'down' }

function outcomeTone(value: string | undefined): 'ok' | 'warning' | 'danger' {
  return value === 'CAN' ? 'ok' : value === 'CANNOT' ? 'danger' : 'warning'
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
  const manageBot = targetCapabilities.data?.bot_operations.MANAGE_ROLE?.outcome ?? 'UNKNOWN'
  const reorderBot = targetCapabilities.data?.bot_operations.REORDER_ROLES?.outcome ?? 'UNKNOWN'
  const isEveryone = selected?.id === guild.guild_id
  const targetBlocked = Boolean(selected?.managed || isEveryone)
  const selectedActionOutcome = targetBlocked ? 'CANNOT' : manageBot

  function blockerText(outcome: string, role?: Role | null) {
    if (role?.managed) return t('access.blocked.managed')
    if (role?.id === guild.guild_id) return t('access.blocked.bot')
    const causes = targetCapabilities.data?.bot_operations.MANAGE_ROLE?.causes ?? []
    if (causes.some((cause) => cause.includes('bot_role_not_above_target'))) return t('access.blocked.hierarchy')
    if (userCanWrite === 'CANNOT' || userCanPlan === 'CANNOT') return t('access.blocked.user')
    if (outcome === 'CANNOT') return t('access.blocked.bot')
    return t('access.blocked.unknown')
  }

  function canPrepare(kind: RoleAction['kind'], role?: Role | null) {
    if (userCanWrite !== 'CAN' || userCanPlan !== 'CAN') return false
    if (kind === 'create') return createBot === 'CAN'
    if (!role || role.managed || role.id === guild.guild_id) return false
    return kind === 'reorder' ? reorderBot === 'CAN' : manageBot === 'CAN'
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
      setProblem(blockerText(action.kind === 'reorder' ? reorderBot : action.kind === 'create' ? createBot : selectedActionOutcome, role))
      return
    }
    setBusy(true)
    setProblem(null)
    try {
      let node: AccessPlanNode
      if (action.kind === 'create') {
        const position = Math.max(0, ...roles.map((item) => item.position)) + 1
        node = {
          logical_key: `ui.role.create.${crypto.randomUUID()}`,
          resource_type: 'ROLE',
          symbol: `role-${crypto.randomUUID()}`,
          properties: { name: action.name.trim(), permissions: '0', position },
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
        <button type="button" className="button primary" disabled={!canPrepare('create')} title={!canPrepare('create') ? blockerText(createBot) : undefined} onClick={() => setAction({ kind: 'create', name: '' })}>{t('roles.create')}</button>
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
            <div className="access-panel-heading"><div><small>{t('roles.details')}</small><strong>{selected.name}</strong></div><Badge tone={outcomeTone(selectedActionOutcome)}>{selected.managed ? t('roles.managed') : selectedActionOutcome}</Badge></div>
            <div className="role-meta-grid">
              <div><span>{t('structure.inspector.discordId')}</span><strong>{selected.id}</strong></div>
              <div><span>{t('structure.inspector.position')}</span><strong>{selected.position}</strong></div>
              <div><span>{t('structure.inspector.freshness')}</span><strong>{selected.freshness}</strong></div>
              <div><span>{t('permissions.rawBitfield')}</span><strong>{selected.permissions}</strong></div>
            </div>
            {selected.managed && <p className="access-callout warning">{t('roles.managedHelp')}</p>}
            {selected.unknown_bits !== '0' && <p className="access-callout warning">{t('roles.unknownBits', { value: selected.unknown_bits })}</p>}
            <section className="permission-chip-section"><h2>{t('permissions.expertRoleFlags')}</h2><div className="permission-chip-cloud">{selected.known_flags.map((flag) => <span key={flag}>{flag}</span>)}</div></section>
            <section className="role-capability-card"><div><small>{t('roles.botCapability')}</small><strong>{selectedActionOutcome === 'CAN' ? t('roles.botCan') : selectedActionOutcome === 'CANNOT' ? t('roles.botBlocked') : t('roles.botUnknown')}</strong></div>{selectedActionOutcome !== 'CAN' && <p>{blockerText(selectedActionOutcome, selected)}</p>}</section>
            <div className="role-action-grid">
              <button type="button" className="button quiet" disabled={!canPrepare('rename', selected)} title={!canPrepare('rename', selected) ? blockerText(manageBot, selected) : undefined} onClick={() => setAction({ kind: 'rename', role: selected, name: selected.name })}>{t('roles.edit')}</button>
              <button type="button" className="button quiet" disabled={!roleAbove || !canPrepare('reorder', selected)} title={!canPrepare('reorder', selected) ? blockerText(reorderBot, selected) : undefined} onClick={() => roleAbove && setAction({ kind: 'reorder', role: selected, position: roleAbove.position, direction: 'up' })}>{t('roles.moveUp')}</button>
              <button type="button" className="button quiet" disabled={!roleBelow || !canPrepare('reorder', selected)} title={!canPrepare('reorder', selected) ? blockerText(reorderBot, selected) : undefined} onClick={() => roleBelow && setAction({ kind: 'reorder', role: selected, position: roleBelow.position, direction: 'down' })}>{t('roles.moveDown')}</button>
              <button type="button" className="button danger" disabled={!canPrepare('delete', selected)} title={!canPrepare('delete', selected) ? blockerText(manageBot, selected) : undefined} onClick={() => setAction({ kind: 'delete', role: selected })}>{t('roles.delete')}</button>
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
