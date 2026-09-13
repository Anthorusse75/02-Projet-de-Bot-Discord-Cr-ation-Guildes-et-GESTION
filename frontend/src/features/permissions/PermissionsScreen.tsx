import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ApiError, apiRequest } from '../../api/client'
import { useRoles, useStructure } from '../../api/queries'
import type { Channel, DashboardCapabilities, Role } from '../../api/types'
import type { DashboardContext } from '../../app/AppShell'
import { Badge, ErrorState, Skeleton } from '../../shared/components/ui'
import { permissionReasonKey } from '../../localization/presentation'
import { createValidatedAccessPlan } from '../access/planDraft'

type PrincipalMode = 'ROLE' | 'MEMBER' | 'NEWCOMER'
type PermissionState = 'ALLOW' | 'INHERIT' | 'DENY'
type Concept = 'VIEW' | 'WRITE' | 'MANAGE' | 'VOICE_JOIN' | 'VOICE_SPEAK' | 'VOICE_STREAM'

type PermissionTrace = {
  step: string
  source_type: string
  source_id: string | null
  allow_bits: string
  deny_bits: string
  before: string
  after: string
  reason_key: string
}

type PermissionDecision = {
  calculated_bits: string
  effective_bits: string
  unknown_bits: string
  decision_status: string
  requested_permission: string | null
  outcome: string
  coverage: string
  freshness: string
  incomplete_reasons: string[]
  trace: PermissionTrace[]
  warnings: string[]
  data_assertion: string
}

type Compilation = {
  allow: string
  deny: string
  known_flags: string[]
  diagnostics: string[]
  registry_version: string
  persisted: false
  discord_mutations: 0
}

type ImpactResult = {
  subjects: Array<{
    subject_id: string
    before: PermissionDecision
    after: PermissionDecision
    added_effective_permissions: string
    removed_effective_permissions: string
  }>
  incomplete_subject_ids: string[]
  warnings: string[]
  persisted: false
  discord_mutations: 0
}

type PermissionPreview = {
  targetId: string
  targetType: 0 | 1
  allowBits: string
  denyBits: string
  allowFlags: string[]
  denyFlags: string[]
  diagnostics: string[]
  decision: PermissionDecision
  impact: ImpactResult | null
}

const concepts: Concept[] = ['VIEW', 'WRITE', 'MANAGE', 'VOICE_JOIN', 'VOICE_SPEAK', 'VOICE_STREAM']
const conceptKey: Record<Concept, string> = {
  VIEW: 'permissions.concept.view',
  WRITE: 'permissions.concept.write',
  MANAGE: 'permissions.concept.manage',
  VOICE_JOIN: 'permissions.concept.voiceJoin',
  VOICE_SPEAK: 'permissions.concept.voiceSpeak',
  VOICE_STREAM: 'permissions.concept.voiceStream',
}

function flattenResources(structure: ReturnType<typeof useStructure>['data']): Channel[] {
  if (!structure) return []
  return [
    ...structure.categories,
    ...structure.categories.flatMap((category) => category.channels),
    ...structure.root_channels,
  ]
}

function resourceLabel(resource: Channel, categories: Channel[]): string {
  if (resource.type === 4) return `▰ ${resource.name}`
  const parent = categories.find((category) => category.id === resource.parent_id)
  return parent ? `${parent.name} / #${resource.name}` : `#${resource.name}`
}

function capabilityTone(outcome: string | undefined): 'ok' | 'warning' | 'danger' {
  return outcome === 'CAN' ? 'ok' : outcome === 'CANNOT' ? 'danger' : 'warning'
}

export function PermissionsScreen() {
  const { t } = useTranslation()
  const { me, guild, capabilities } = useOutletContext<DashboardContext>()
  const navigate = useNavigate()
  const structure = useStructure(me.user.discord_user_id, guild.guild_id)
  const rolesQuery = useRoles(me.user.discord_user_id, guild.guild_id)
  const [expert, setExpert] = useState(false)
  const [principalMode, setPrincipalMode] = useState<PrincipalMode>('ROLE')
  const [roleId, setRoleId] = useState('')
  const [memberId, setMemberId] = useState('')
  const [resourceId, setResourceId] = useState('')
  const [states, setStates] = useState<Record<Concept, PermissionState>>(() => Object.fromEntries(concepts.map((concept) => [concept, 'INHERIT'])) as Record<Concept, PermissionState>)
  const [decision, setDecision] = useState<PermissionDecision | null>(null)
  const [preview, setPreview] = useState<PermissionPreview | null>(null)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)

  const roles = useMemo(() => [...(rolesQuery.data?.roles ?? [])].sort((a, b) => b.position - a.position || a.name.localeCompare(b.name)), [rolesQuery.data])
  const selectedRole = roles.find((role) => role.id === roleId) ?? null
  const resources = useMemo(() => flattenResources(structure.data), [structure.data])
  const selectedResource = resources.find((resource) => resource.id === resourceId) ?? null
  const resourceCapabilities = useQuery({
    enabled: Boolean(resourceId),
    queryKey: ['did', me.user.discord_user_id, guild.guild_id, 'dashboard-capabilities', 'permission-resource', resourceId],
    queryFn: () => apiRequest<DashboardCapabilities>(`/api/v1/guilds/${guild.guild_id}/dashboard-capabilities?resource_id=${encodeURIComponent(resourceId)}`),
  })

  const userCanWrite = capabilities?.user_capabilities['permissions.write']?.outcome ?? 'UNKNOWN'
  const userCanPlan = capabilities?.user_capabilities['plans.create']?.outcome ?? 'UNKNOWN'
  const botOverwrite = resourceCapabilities.data?.bot_operations.MANAGE_OVERWRITES?.outcome ?? 'UNKNOWN'
  const categories = structure.data?.categories ?? []
  const allowConcepts = concepts.filter((concept) => states[concept] === 'ALLOW')
  const denyConcepts = concepts.filter((concept) => states[concept] === 'DENY')
  const targetId = principalMode === 'ROLE' ? roleId : principalMode === 'MEMBER' ? memberId.trim() : ''
  const targetType: 0 | 1 = principalMode === 'MEMBER' ? 1 : 0

  function resetComputed() {
    setDecision(null)
    setPreview(null)
    setProblem(null)
  }

  function setConceptState(concept: Concept, state: PermissionState) {
    setStates((current) => ({ ...current, [concept]: state }))
    setPreview(null)
    setProblem(null)
  }

  function explanationBody() {
    if (principalMode === 'ROLE') return { view_as: 'VIEW_AS_ROLE', subject_id: null, role_id: roleId || null, resource_id: resourceId || null }
    if (principalMode === 'MEMBER') return { view_as: 'VIEW_AS_MEMBER', subject_id: memberId.trim() || null, role_id: null, resource_id: resourceId || null }
    return { view_as: 'VIEW_AS_NEWCOMER', subject_id: null, role_id: null, resource_id: resourceId || null }
  }

  async function diagnose(): Promise<PermissionDecision | null> {
    setProblem(null)
    if (!resourceId) { setProblem(t('permissions.selectResource')); return null }
    if (principalMode !== 'NEWCOMER' && !targetId) { setProblem(t('permissions.selectPrincipal')); return null }
    setBusy(true)
    try {
      const result = await apiRequest<PermissionDecision>(`/api/v1/guilds/${guild.guild_id}/permissions/explain`, { method: 'POST', body: explanationBody() })
      setDecision(result)
      return result
    } catch (error) {
      setProblem(error instanceof ApiError && error.status === 403 ? t('access.blocked.user') : t('errors.generic', { requestId: error instanceof ApiError ? error.requestId : 'unknown' }))
      return null
    } finally {
      setBusy(false)
    }
  }

  async function compile(selected: Concept[]): Promise<Compilation> {
    if (selected.length === 0) return { allow: '0', deny: '0', known_flags: [], diagnostics: [], registry_version: '', persisted: false, discord_mutations: 0 }
    return apiRequest<Compilation>(`/api/v1/guilds/${guild.guild_id}/permissions/simple/compile`, { method: 'POST', body: { concepts: selected } })
  }

  async function previewImpact() {
    setProblem(null)
    setPreview(null)
    if (!resourceId) { setProblem(t('permissions.selectResource')); return }
    if (principalMode === 'NEWCOMER' || !targetId) { setProblem(t('permissions.selectPrincipal')); return }
    if (allowConcepts.length === 0 && denyConcepts.length === 0) { setProblem(t('permissions.noIntent')); return }
    setBusy(true)
    try {
      const [allow, deny, current] = await Promise.all([
        compile(allowConcepts),
        compile(denyConcepts),
        apiRequest<PermissionDecision>(`/api/v1/guilds/${guild.guild_id}/permissions/explain`, { method: 'POST', body: explanationBody() }),
      ])
      let impact: ImpactResult | null = null
      if (principalMode === 'MEMBER') {
        impact = await apiRequest<ImpactResult>(`/api/v1/guilds/${guild.guild_id}/permissions/simulate`, {
          method: 'POST',
          body: {
            resource_id: resourceId,
            subject_ids: [targetId],
            proposed_overwrites: [{ target_id: targetId, target_type: targetType, allow: allow.allow, deny: deny.allow }],
          },
        })
      }
      setDecision(current)
      setPreview({
        targetId,
        targetType,
        allowBits: allow.allow,
        denyBits: deny.allow,
        allowFlags: allow.known_flags,
        denyFlags: deny.known_flags,
        diagnostics: [...allow.diagnostics, ...deny.diagnostics],
        decision: current,
        impact,
      })
    } catch (error) {
      setProblem(error instanceof ApiError && error.status === 403 ? t('access.blocked.user') : t('errors.generic', { requestId: error instanceof ApiError ? error.requestId : 'unknown' }))
    } finally {
      setBusy(false)
    }
  }

  function proposalBlocker(): string | null {
    if (userCanWrite === 'CANNOT' || userCanPlan === 'CANNOT') return t('access.blocked.user')
    if (userCanWrite !== 'CAN' || userCanPlan !== 'CAN') return t('access.blocked.unknown')
    if (botOverwrite === 'CANNOT') return t('access.blocked.bot')
    if (botOverwrite !== 'CAN') return t('access.blocked.unknown')
    return null
  }

  async function prepareProposal() {
    if (!preview || !selectedResource || principalMode === 'NEWCOMER') return
    const blocker = proposalBlocker()
    if (blocker) { setProblem(blocker); return }
    setBusy(true)
    setProblem(null)
    try {
      await createValidatedAccessPlan(guild.guild_id, [{
        logical_key: `ui.permission.overwrite.${selectedResource.id}.${preview.targetId}`,
        resource_type: 'OVERWRITE',
        properties: { target_type: preview.targetType, allow: preview.allowBits, deny: preview.denyBits },
        relations: [
          { name: 'channel', kind: 'DISCORD_ID', value: selectedResource.id },
          { name: 'subject', kind: 'DISCORD_ID', value: preview.targetId },
        ],
      }])
      navigate(`/guild/${guild.guild_id}/plans`)
    } catch (error) {
      setProblem(error instanceof ApiError && error.status === 403 ? t('access.blocked.user') : t('errors.generic', { requestId: error instanceof ApiError ? error.requestId : 'unknown' }))
    } finally {
      setBusy(false)
    }
  }

  if (structure.isLoading || rolesQuery.isLoading) return <Skeleton />
  if (structure.isError) return <ErrorState retry={() => void structure.refetch()} />
  if (rolesQuery.isError) return <ErrorState retry={() => void rolesQuery.refetch()} />

  const activeDecision = preview?.decision ?? decision
  const adminWarning = activeDecision?.warnings.includes('permissions.warning.administratorBypassesOverwrites') ?? false
  const blocker = proposalBlocker()
  const memberImpact = preview?.impact?.subjects[0]

  return (
    <section className="access-page permissions-workbench">
      <header className="access-hero">
        <div><p className="access-eyebrow">{t('access.eyebrow')}</p><h1>{t('permissions.title')}</h1><p>{t('permissions.subtitle')}</p></div>
        <div className="access-mode-switch" role="tablist" aria-label={t('permissions.title')}>
          <button type="button" role="tab" aria-selected={!expert} className={!expert ? 'active' : ''} onClick={() => setExpert(false)}>{t('permissions.mode.simple')}</button>
          <button type="button" role="tab" aria-selected={expert} className={expert ? 'active' : ''} onClick={() => setExpert(true)}>{t('permissions.mode.expert')}</button>
        </div>
      </header>

      <div className="permissions-layout">
        <article className="access-panel permission-config-panel">
          <div className="access-panel-heading"><div><small>{t('permissions.current')}</small><strong>{selectedResource?.name ?? t('permissions.selectResource')}</strong></div></div>
          <div className="access-form-grid">
            <label className="field"><span>{t('permissions.resource')}</span><select value={resourceId} onChange={(event) => { setResourceId(event.target.value); resetComputed() }}><option value="">—</option>{resources.map((resource) => <option key={resource.id} value={resource.id}>{resourceLabel(resource, categories)}</option>)}</select></label>
            <label className="field"><span>{t('permissions.principalType')}</span><select value={principalMode} onChange={(event) => { setPrincipalMode(event.target.value as PrincipalMode); resetComputed() }}><option value="ROLE">{t('permissions.principal.role')}</option><option value="MEMBER">{t('permissions.principal.member')}</option><option value="NEWCOMER">{t('permissions.principal.newcomer')}</option></select></label>
            {principalMode === 'ROLE' && <label className="field"><span>{t('permissions.role')}</span><select value={roleId} onChange={(event) => { setRoleId(event.target.value); resetComputed() }}><option value="">—</option>{roles.map((role) => <option key={role.id} value={role.id}>{role.name}</option>)}</select></label>}
            {principalMode === 'MEMBER' && <label className="field"><span>{t('permissions.memberId')}</span><input value={memberId} inputMode="numeric" pattern="[1-9][0-9]{0,19}" onChange={(event) => { setMemberId(event.target.value); resetComputed() }} /></label>}
          </div>

          {!expert ? <>
            <p className="access-help">{t('permissions.simpleHelp')}</p>
            <div className="permission-intent-list">
              {concepts.map((concept) => <div className="permission-intent-row" key={concept}><strong>{t(conceptKey[concept])}</strong><div className="tri-state" role="group" aria-label={t(conceptKey[concept])}>{(['ALLOW', 'INHERIT', 'DENY'] as PermissionState[]).map((state) => <button key={state} type="button" className={states[concept] === state ? `active ${state.toLowerCase()}` : ''} aria-pressed={states[concept] === state} onClick={() => setConceptState(concept, state)}>{t(`permissions.state.${state.toLowerCase()}`)}</button>)}</div></div>)}
            </div>
            {(allowConcepts.includes('WRITE') || denyConcepts.includes('WRITE')) && <p className="access-callout warning">{t('permissions.writeDiagnostic')}</p>}
          </> : <section className="expert-permission-panel">
            {selectedRole && <div className="expert-role-flags"><div><small>{t('permissions.expertRoleFlags')}</small><strong>{selectedRole.name}</strong></div><code>{selectedRole.permissions}</code><div className="permission-chip-cloud">{selectedRole.known_flags.map((flag) => <span key={flag}>{flag}</span>)}</div>{selectedRole.unknown_bits !== '0' && <p className="access-callout warning">{t('roles.unknownBits', { value: selectedRole.unknown_bits })}</p>}</div>}
            {!activeDecision && <p className="access-help">{t('permissions.diagnose')}</p>}
          </section>}

          <div className="permission-actions"><button type="button" className="button quiet" disabled={busy} onClick={() => void diagnose()}>{t('permissions.diagnose')}</button>{!expert && principalMode !== 'NEWCOMER' && <button type="button" className="button primary" disabled={busy} onClick={() => void previewImpact()}>{t('permissions.preview')}</button>}</div>
          {problem && <p className="access-callout danger" role="alert">{problem}</p>}
        </article>

        <article className="access-panel permission-inspector-panel">
          <div className="access-panel-heading"><div><small>{t('permissions.diagnosis')}</small><strong>{activeDecision ? activeDecision.outcome : '—'}</strong></div>{activeDecision && <Badge tone={activeDecision.outcome === 'ALLOW' || activeDecision.outcome === 'CAN' ? 'ok' : activeDecision.outcome === 'DENY' || activeDecision.outcome === 'CANNOT' ? 'danger' : 'warning'}>{activeDecision.decision_status}</Badge>}</div>
          {!activeDecision ? <div className="access-empty"><span>◈</span><p>{t('permissions.diagnose')}</p></div> : <>
            <div className="permission-result-grid"><div><span>{t('permissions.effectiveBits', { value: activeDecision.effective_bits })}</span><strong>{activeDecision.effective_bits}</strong></div><div><span>{t('permissions.coverage', { value: activeDecision.coverage })}</span><strong>{activeDecision.coverage}</strong></div><div><span>{t('permissions.freshness', { value: activeDecision.freshness })}</span><strong>{activeDecision.freshness}</strong></div><div><span>{t('permissions.rawBitfield')}</span><strong>{activeDecision.calculated_bits}</strong></div></div>
            {adminWarning && <p className="access-callout danger">{t('permissions.adminWarning')}</p>}
            {activeDecision.warnings.filter((warning) => warning !== 'permissions.warning.administratorBypassesOverwrites').map((warning) => <p className="access-callout warning" key={warning}>{t('permissions.warningGeneric')}</p>)}
            {expert && <section className="permission-trace"><h2>{t('permissions.trace')}</h2>{activeDecision.trace.map((item, index) => <article key={`${item.step}-${index}`}><div><Badge>{item.step}</Badge><strong>{t('permissions.traceStep', { index: index + 1 })}</strong></div><p>{t(permissionReasonKey(item.reason_key))}</p><small>{t('permissions.source', { type: item.source_type, id: item.source_id ?? '—' })}</small><code>{t('permissions.beforeAfter', { before: item.before, after: item.after })}</code><small>{t('permissions.overwriteBits', { allow: item.allow_bits, deny: item.deny_bits })}</small></article>)}</section>}
          </>}
        </article>
      </div>

      {preview && <article className="access-panel permission-impact-panel">
        <div className="access-panel-heading"><div><small>{t('permissions.impact')}</small><strong>{selectedResource?.name}</strong></div><Badge tone={capabilityTone(botOverwrite)}>{botOverwrite === 'CAN' ? t('permissions.botCan') : botOverwrite === 'CANNOT' ? t('permissions.botBlocked') : t('permissions.botUnknown')}</Badge></div>
        <div className="overwrite-preview"><div><span>{t('permissions.allowFlags', { flags: preview.allowFlags.join(', ') || '—' })}</span><code>{preview.allowBits}</code></div><div><span>{t('permissions.denyFlags', { flags: preview.denyFlags.join(', ') || '—' })}</span><code>{preview.denyBits}</code></div></div>
        {preview.diagnostics.length > 0 && <p className="access-callout warning">{t('permissions.writeDiagnostic')}</p>}
        {memberImpact ? <div className="member-impact"><h2>{t('permissions.memberImpact')}</h2><p>{t('permissions.added', { value: memberImpact.added_effective_permissions })}</p><p>{t('permissions.removed', { value: memberImpact.removed_effective_permissions })}</p></div> : <p className="access-help">{t('permissions.roleImpactNote')}</p>}
        {adminWarning && <p className="access-callout danger">{t('permissions.adminWarning')}</p>}
        {blocker && <p className="access-callout danger">{blocker}</p>}
        <div className="button-row"><button type="button" className="button primary" disabled={busy || Boolean(blocker)} title={blocker ?? undefined} onClick={() => void prepareProposal()}>{t('permissions.propose')}</button></div>
      </article>}
    </section>
  )
}
