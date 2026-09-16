import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { apiRequest } from '../../api/client'
import { usePolicies, useRoles, useStructure } from '../../api/queries'
import type { CapabilityOutcome, LogicalGroup, Policy, PolicyAccess, PolicyPreview, PolicyPreviewEntry, PolicyResolution, PolicyVersion } from '../../api/types'
import type { DashboardContext } from '../../app/AppShell'
import { Badge, ErrorState, Skeleton } from '../../shared/components/ui'
import { apiProblem } from './errors'
import {
  clonePolicyDefinition,
  compatibleNativePolicies,
  createDefinitionFromNative,
  isPolicyCompatible,
  nativePolicies,
  nativePolicyByTag,
  type NativePolicy,
  type BotFunction,
  type PolicyMode,
  type PolicyDraftDefinition,
  type PolicyTarget,
} from './catalog'
import { buildPolicyTargets, targetKey } from './targets'

type Selection = { kind: 'NATIVE'; native: NativePolicy } | { kind: 'CUSTOM'; policy: Policy }
type EditorState = {
  name: string; description: string; priority: number; roleIds: string[]
  reactionMode: PolicyMode; threadMode: PolicyMode; includeStaff: boolean; staffRoleIds: string[]
  botId: string; botFunctions: BotFunction[]
}
type BotAudit = { user_id: string; status: string; incomplete_reasons: string[] }
type BotMinimum = {
  functions: BotFunction[]; outcome: CapabilityOutcome; required_permissions: string[]
  missing_permissions: string[]; causes: string[]; remediations: string[]; warnings: string[]
}
type BotAccessMap = { channels: Array<{ channel_id: string; status: string; minimum?: BotMinimum }> }

const emptyEditor = (): EditorState => ({
  name: '', description: '', priority: 0, roleIds: [], reactionMode: 'ONLY',
  threadMode: 'INHERIT', includeStaff: false, staffRoleIds: [], botId: '', botFunctions: [],
})

const lifecycleTone = { DRAFT: 'warning', ACTIVE: 'ok', DISABLED: 'neutral', RETIRED: 'danger' } as const

function partialMember(value: string): string {
  return value.length <= 4 ? value : `…${value.slice(-4)}`
}

function sourcePolicyId(policy: Policy): string | null {
  return policy.metadata.tags.find((tag) => tag.startsWith('source-policy:'))?.slice('source-policy:'.length) ?? null
}

function roleIds(policy: Policy): string[] {
  const audience = policy.effects.find((effect) => effect.audience)?.audience
  if (audience) return audience.role_ids
  const condition = policy.conditions.find((item) => item.kind === 'ROLE_MATCH')
  return condition?.kind === 'ROLE_MATCH' ? condition.role_ids : []
}

function modeFromPolicy(policy: Policy, access: PolicyAccess): PolicyMode {
  const effects = policy.effects.filter((effect) => effect.access === access)
  if (effects.length === 0) return 'INHERIT'
  if (effects.some((effect) => effect.decision === 'DENY' && !effect.audience)) return 'NONE'
  if (effects.some((effect) => effect.audience)) return 'ONLY'
  return 'EVERYONE'
}

function botFunctions(policy: Policy): BotFunction[] {
  const tag = policy.metadata.tags.find((value) => value.startsWith('bot-functions:'))
  if (tag) return tag.slice('bot-functions:'.length).split(',').map((value) => value.toUpperCase() as BotFunction)
  const accesses = new Set(policy.effects.map((effect) => effect.access))
  const result: BotFunction[] = []
  if (accesses.has('READ_HISTORY') || accesses.has('VIEW')) result.push('READ')
  if (accesses.has('SEND') || accesses.has('WRITE')) result.push('WRITE')
  if (accesses.has('MANAGE_CHANNEL') || accesses.has('MANAGE')) result.push('MANAGE')
  if (accesses.has('CREATE_THREAD') || accesses.has('PARTICIPATE_THREAD')) result.push('THREADS')
  if (accesses.has('CONNECT') || accesses.has('SPEAK')) result.push('VOCAL')
  return result
}

function editorFromPolicy(policy: Policy): EditorState {
  const botMatch = policy.conditions.find((condition) => condition.kind === 'BOT_MATCH')
  return {
    ...emptyEditor(), name: policy.name, description: policy.description, priority: policy.priority,
    roleIds: roleIds(policy), reactionMode: modeFromPolicy(policy, 'REACT'),
    threadMode: modeFromPolicy(policy, 'CREATE_THREAD'),
    includeStaff: policy.metadata.tags.includes('staff-explicit:true'),
    botId: botMatch?.kind === 'BOT_MATCH' ? botMatch.bot_user_ids[0] ?? '' : '',
    botFunctions: botFunctions(policy),
  }
}

function policyFamily(policy: Policy): NativePolicy['family'] {
  const native = nativePolicyByTag(policy)
  if (native) return native.family
  if (policy.effects.some((effect) => effect.access === 'WRITE')) return 'WRITING'
  if (policy.effects.some((effect) => effect.access === 'VIEW')) return 'VISIBILITY'
  return 'AUDIENCE'
}

function customDefinition(policy: Policy, editor: EditorState): PolicyDraftDefinition {
  const conditions = policy.conditions.map((condition) => {
    if (condition.kind === 'ROLE_MATCH') return { ...condition, role_ids: editor.roleIds }
    if (condition.kind === 'BOT_MATCH') return { ...condition, bot_user_ids: [editor.botId] }
    return condition
  })
  const effects = policy.effects.map((effect) => effect.audience
    ? { ...effect, audience: { ...effect.audience, role_ids: editor.roleIds } }
    : effect)
  return {
    policy_type: 'ACCESS_CONTROL', contract_version: 1,
    name: editor.name.trim(), description: editor.description.trim(), priority: editor.priority,
    scope_type: policy.scope_type, scope_id: policy.scope_id, conditions, effects,
    metadata: { ...policy.metadata, summary: editor.description.trim() || editor.name.trim() },
  }
}

export function PoliciesScreen() {
  const { t, i18n } = useTranslation()
  const { me, guild, capabilities } = useOutletContext<DashboardContext>()
  const navigate = useNavigate()
  const client = useQueryClient()
  const canRead = capabilities?.user_capabilities['policies.read']?.outcome ?? 'UNKNOWN'
  const canCreate = capabilities?.user_capabilities['policies.create']?.outcome ?? 'UNKNOWN'
  const canUpdate = capabilities?.user_capabilities['policies.update']?.outcome ?? 'UNKNOWN'
  const canPrepare = capabilities?.user_capabilities['policies.activate']?.outcome === 'CAN'
    && capabilities?.user_capabilities['plans.create']?.outcome === 'CAN'
  const policyWorkspaceEnabled = canRead === 'CAN'
  const policiesQuery = usePolicies(me.user.discord_user_id, guild.guild_id, policyWorkspaceEnabled)
  const rolesQuery = useRoles(me.user.discord_user_id, guild.guild_id, policyWorkspaceEnabled)
  const structureQuery = useStructure(me.user.discord_user_id, guild.guild_id, false, policyWorkspaceEnabled)
  const groupsQuery = useQuery({
    enabled: policyWorkspaceEnabled,
    queryKey: ['did', me.user.discord_user_id, guild.guild_id, 'logical-groups'],
    queryFn: () => apiRequest<{groups:LogicalGroup[]}>(`/api/v1/guilds/${guild.guild_id}/logical-groups`),
  })
  const [expert, setExpert] = useState(false)
  const [targetValue, setTargetValue] = useState('GUILD:*')
  const [selection, setSelection] = useState<Selection | null>(null)
  const [editor, setEditor] = useState<EditorState>(emptyEditor)
  const [preview, setPreview] = useState<PolicyPreview | null>(null)
  const [explanation, setExplanation] = useState<PolicyResolution | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [remediationKey, setRemediationKey] = useState<string | null>(null)

  const roles = useMemo(() => [...(rolesQuery.data?.roles ?? [])].filter((role) => !role.managed).sort((a, b) => b.position - a.position), [rolesQuery.data])
  const targets = useMemo<PolicyTarget[]>(
    () => buildPolicyTargets(guild, roles, groupsQuery.data?.groups, structureQuery.data),
    [groupsQuery.data, guild, roles, structureQuery.data],
  )
  const selectedTarget = targets.find((target) => targetKey(target) === targetValue) ?? targets[0] ?? null
  const channelTypes = useMemo(() => new Map(targets.filter((target) => target.scopeType === 'CHANNEL' && target.scopeId).map((target) => [target.scopeId as string, target.kind === 'VOICE_CHANNEL' ? 2 : 0])), [targets])
  const customPolicies = (policiesQuery.data?.policies ?? []).filter((policy) => isPolicyCompatible(policy, selectedTarget, channelTypes))
  const availableNatives = compatibleNativePolicies(selectedTarget?.kind ?? null)
  const selectedPolicy = selection?.kind === 'CUSTOM' ? selection.policy : null
  const activeNative = selection?.kind === 'NATIVE' ? selection.native : selectedPolicy ? nativePolicyByTag(selectedPolicy) : undefined
  const botsQuery = useQuery({
    enabled: policyWorkspaceEnabled && activeNative?.id === 'bot_minimal',
    queryKey: ['did', me.user.discord_user_id, guild.guild_id, 'bots', 'audit'],
    queryFn: () => apiRequest<{ bots: BotAudit[] }>(`/api/v1/guilds/${guild.guild_id}/bots/audit`),
  })
  const botAccessQuery = useQuery({
    enabled: activeNative?.id === 'bot_minimal' && Boolean(editor.botId && selectedTarget?.scopeId && editor.botFunctions.length),
    queryKey: ['did', me.user.discord_user_id, guild.guild_id, 'bots', editor.botId, 'minimal', selectedTarget?.scopeId, editor.botFunctions.join(',')],
    queryFn: () => apiRequest<BotAccessMap>(`/api/v1/guilds/${guild.guild_id}/bots/${editor.botId}/access-map?functions=${editor.botFunctions.join(',')}`),
  })
  const versionsQuery = useQuery({
    enabled: historyOpen && Boolean(selectedPolicy),
    queryKey: ['did', me.user.discord_user_id, guild.guild_id, 'policies', selectedPolicy?.policy_id ?? 'none', 'versions'],
    queryFn: () => apiRequest<{versions:PolicyVersion[]}>(`/api/v1/guilds/${guild.guild_id}/policies/${selectedPolicy?.policy_id}/versions`),
  })

  function chooseNative(native: NativePolicy) {
    setSelection({ kind: 'NATIVE', native })
    setEditor({ ...emptyEditor(), name: t(native.titleKey), description: t(native.summaryKey), botFunctions: native.id === 'bot_minimal' ? ['READ'] : [] })
    setPreview(null); setExplanation(null); setProblem(null); setNotice(null); setHistoryOpen(false)
  }

  function chooseCustom(policy: Policy) {
    const target = targets.find((item) => item.scopeType === policy.scope_type && item.scopeId === policy.scope_id)
    if (target) setTargetValue(targetKey(target))
    setSelection({ kind: 'CUSTOM', policy })
    setEditor(editorFromPolicy(policy))
    setPreview(null); setExplanation(null); setProblem(null); setNotice(null); setHistoryOpen(false)
  }

  async function createDraft(definition: PolicyDraftDefinition, noticeKey: string) {
    setBusy(true); setProblem(null); setNotice(null)
    try {
      const created = await apiRequest<Policy>(`/api/v1/guilds/${guild.guild_id}/policies`, { method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() }, body: definition })
      await client.invalidateQueries({ queryKey: ['did', me.user.discord_user_id, guild.guild_id, 'policies'] })
      chooseCustom(created); setNotice(t(noticeKey))
      return created
    } catch (error) { setProblem(apiProblem(error, t)); return null }
    finally { setBusy(false) }
  }

  function nativeDefinition(native: NativePolicy, target: PolicyTarget): PolicyDraftDefinition {
    return createDefinitionFromNative(native, target, editor.roleIds, {
      ...editor,
      ...(selectedPolicy && sourcePolicyId(selectedPolicy) ? { sourcePolicyId: sourcePolicyId(selectedPolicy) as string } : {}),
    })
  }

  async function save() {
    if (!selection || !selectedTarget) return
    if (!editor.name.trim()) { setProblem(t('policies.error.nameRequired')); return }
    if (activeNative?.id === 'bot_minimal' && (!editor.botId || editor.botFunctions.length === 0)) {
      setProblem(t('policies.error.botConfigurationRequired')); return
    }
    if (activeNative?.id === 'private_voice' && editor.includeStaff && editor.staffRoleIds.length === 0) {
      setProblem(t('policies.error.staffConfigurationRequired')); return
    }
    const modeNeedsAudience = ['reactions', 'mentions'].includes(activeNative?.id ?? '') && editor.reactionMode === 'ONLY'
    const requiresAudience = activeNative?.editorKind !== 'BOT'
      && (activeNative?.editorKind === 'AUDIENCE' || !activeNative?.editorKind || modeNeedsAudience
        || selection.kind === 'CUSTOM' && (selection.policy.conditions.some((condition) => condition.kind === 'ROLE_MATCH')
          || selection.policy.effects.some((effect) => Boolean(effect.audience))))
    if (requiresAudience && editor.roleIds.length === 0) { setProblem(t('policies.error.audienceRequired')); return }
    if (selection.kind === 'NATIVE') {
      await createDraft(nativeDefinition(selection.native, selectedTarget), 'policies.notice.created')
      return
    }
    if (selection.policy.lifecycle_state !== 'DRAFT') return
    setBusy(true); setProblem(null); setNotice(null)
    try {
      const updated = await apiRequest<Policy>(`/api/v1/guilds/${guild.guild_id}/policies/${selection.policy.policy_id}`, {
        method: 'PATCH', headers: { 'Idempotency-Key': crypto.randomUUID() },
        body: { ...(activeNative ? nativeDefinition(activeNative, selectedTarget) : customDefinition(selection.policy, editor)), expected_revision: selection.policy.revision },
      })
      await client.invalidateQueries({ queryKey: ['did', me.user.discord_user_id, guild.guild_id, 'policies'] })
      chooseCustom(updated); setNotice(t('policies.notice.saved'))
    } catch (error) { setProblem(apiProblem(error, t)) }
    finally { setBusy(false) }
  }

  async function duplicate(policy: Policy) {
    await createDraft(clonePolicyDefinition(policy, t('policies.copyName', { name: policy.name })), 'policies.notice.duplicated')
  }

  async function draftFromVersion(version: PolicyVersion) {
    const snapshot = version.snapshot
    await createDraft(clonePolicyDefinition(snapshot, t('policies.versionName', { name: snapshot.name, revision: version.revision })), 'policies.notice.versionDraft')
    setHistoryOpen(false)
  }

  async function loadPreview() {
    if (!selectedPolicy || selectedPolicy.lifecycle_state !== 'DRAFT') return
    setBusy(true); setProblem(null); setPreview(null); setExplanation(null)
    try {
      const result = await apiRequest<PolicyPreview>(`/api/v1/guilds/${guild.guild_id}/policies/${selectedPolicy.policy_id}/preview`, { method: 'POST' })
      setPreview(result)
    } catch (error) { setProblem(apiProblem(error, t)) }
    finally { setBusy(false) }
  }

  async function explain(entry: PolicyPreviewEntry) {
    setBusy(true); setProblem(null)
    try {
      const result = await apiRequest<PolicyResolution>(`/api/v1/guilds/${guild.guild_id}/policy-resolution`, { method: 'POST', body: {
        subject_id: entry.target.subject_id, target_scope_type: entry.target.scope_type,
        target_scope_id: entry.target.scope_id, requested_access: entry.target.requested_access,
      } })
      setExplanation(result)
    } catch (error) { setProblem(apiProblem(error, t)) }
    finally { setBusy(false) }
  }

  function planBlocker(): string | null {
    if (!preview) return t('policies.plan.previewFirst')
    if (!canPrepare) return t('policies.error.prepareDenied')
    if (preview.impact.accuracy !== 'EXACT') return t('policies.plan.exactRequired')
    if (preview.entries.some((entry) => entry.proposed.outcome === 'BLOCKED' || entry.proposed.outcome === 'UNKNOWN')) return t('policies.plan.unresolved')
    return null
  }

  async function preparePlan() {
    if (!selectedPolicy || !preview) return
    const blocker = planBlocker(); if (blocker) { setProblem(blocker); return }
    setBusy(true); setProblem(null)
    try {
      await apiRequest(`/api/v1/guilds/${guild.guild_id}/policies/${selectedPolicy.policy_id}/plan`, {
        method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() }, body: { expected_revision: selectedPolicy.revision },
      })
      navigate(`/guild/${guild.guild_id}/plans`)
    } catch (error) { setProblem(apiProblem(error, t)) }
    finally { setBusy(false) }
  }

  function policyName(id: string): string {
    return policiesQuery.data?.policies.find((policy) => policy.policy_id === id)?.name ?? t('policies.source.unknown')
  }

  if (!capabilities) return <Skeleton />
  if (!policyWorkspaceEnabled) return <section className="access-page"><header className="access-hero"><div><p className="access-eyebrow">{t('access.eyebrow')}</p><h1>{t('policies.title')}</h1></div></header><p className="access-callout danger" role="alert">{t('policies.error.denied')}</p></section>
  if (policiesQuery.isLoading || rolesQuery.isLoading || structureQuery.isLoading) return <Skeleton />
  if (policiesQuery.isError || rolesQuery.isError || structureQuery.isError) return <ErrorState retry={() => { void policiesQuery.refetch(); void rolesQuery.refetch(); void structureQuery.refetch() }} />
  const visibleDefinition = selection?.kind === 'NATIVE' && activeNative && selectedTarget
    ? nativeDefinition(activeNative, selectedTarget)
    : selectedPolicy
      ? activeNative && selectedTarget ? nativeDefinition(activeNative, selectedTarget) : customDefinition(selectedPolicy, editor)
      : null
  const canSave = selection?.kind === 'NATIVE' ? canCreate === 'CAN' : selectedPolicy?.lifecycle_state === 'DRAFT' && canUpdate === 'CAN'
  const blocker = planBlocker()
  const botMinimum = botAccessQuery.data?.channels.find((channel) => channel.channel_id === selectedTarget?.scopeId)?.minimum
  const editorDisabled = selectedPolicy?.lifecycle_state !== 'DRAFT' && selection?.kind === 'CUSTOM'

  return <section className="access-page policies-workbench">
    <header className="access-hero">
      <div><p className="access-eyebrow">{t('access.eyebrow')}</p><h1>{t('policies.title')}</h1><p>{t('policies.subtitle')}</p></div>
      <div className="access-mode-switch" role="tablist" aria-label={t('policies.mode.label')}>
        <button type="button" role="tab" aria-selected={!expert} className={!expert ? 'active' : ''} onClick={() => setExpert(false)}>{t('policies.mode.simple')}</button>
        <button type="button" role="tab" aria-selected={expert} className={expert ? 'active' : ''} onClick={() => setExpert(true)}>{t('policies.mode.expert')}</button>
      </div>
    </header>

    <article className="access-panel policy-target-panel">
      <div><small>{t('policies.step.target')}</small><h2>{t('policies.target.title')}</h2><p>{t('policies.target.help')}</p></div>
      <label className="field"><span>{t('policies.target.label')}</span><select value={targetValue} onChange={(event) => { setTargetValue(event.target.value); setSelection(null); setPreview(null); setExplanation(null) }}>
        {targets.map((target) => <option key={targetKey(target)} value={targetKey(target)}>{t(`policies.target.kind.${target.kind}`)} · {target.label}</option>)}
      </select></label>
    </article>

    <div className="policy-layout">
      <article className="access-panel policy-catalog-panel">
        <div className="access-panel-heading"><div><small>{t('policies.step.policy')}</small><strong>{t('policies.catalog.title')}</strong></div><Badge>{t('policies.catalog.count', { count: availableNatives.length + customPolicies.length })}</Badge></div>
        <section aria-labelledby="native-policy-title"><h2 id="native-policy-title">{t('policies.native.title')}</h2><div className="policy-card-list">
          {availableNatives.map((native) => <button type="button" className={selection?.kind === 'NATIVE' && selection.native.id === native.id ? 'policy-card selected' : 'policy-card'} key={native.id} onClick={() => chooseNative(native)}>
            <span className="policy-card-heading"><strong>{t(native.titleKey)}</strong><Badge>{t('policies.origin.did')}</Badge></span><span>{t(native.summaryKey)}</span><small>{t(`policies.family.${native.family}`)} · {selectedTarget ? `${t(`policies.target.kind.${selectedTarget.kind}`)} — ${selectedTarget.label}` : ''} · {t('policies.version.catalog')}</small>
          </button>)}
        </div></section>
        <section aria-labelledby="custom-policy-title"><h2 id="custom-policy-title">{t('policies.custom.title')}</h2><div className="policy-card-list">
          {customPolicies.length === 0 && <p className="access-help">{t('policies.custom.empty')}</p>}
          {customPolicies.map((policy) => <button type="button" className={selectedPolicy?.policy_id === policy.policy_id ? 'policy-card selected' : 'policy-card'} key={policy.policy_id} onClick={() => chooseCustom(policy)}>
            <span className="policy-card-heading"><strong>{policy.name}</strong><Badge tone={lifecycleTone[policy.lifecycle_state]}>{t(`policies.lifecycle.${policy.lifecycle_state}`)}</Badge></span><span>{policy.metadata.summary}</span><small>{t(`policies.family.${policyFamily(policy)}`)} · {selectedTarget ? `${t(`policies.target.kind.${selectedTarget.kind}`)} — ${selectedTarget.label}` : ''}</small><small>{t('policies.origin.custom')} · {t('policies.revision', { revision: policy.revision })}</small>
            <small>{sourcePolicyId(policy) ? t('policies.inherited.source') : policy.scope_type === 'CATEGORY' || policy.scope_type === 'LOGICAL_GROUP' ? t('policies.inherited.children') : t('policies.inherited.none')} · {preview?.policy_id === policy.policy_id ? t('policies.conflicts.count', { count: preview.impact.conflicts }) : t('policies.conflicts.notAnalysed')}</small>
          </button>)}
        </div></section>
      </article>

      <article className="access-panel policy-editor-panel">
        {!selection ? <div className="access-empty"><span>◇</span><p>{t('policies.editor.empty')}</p></div> : <>
          <div className="access-panel-heading"><div><small>{selection.kind === 'NATIVE' ? t('policies.origin.did') : t('policies.origin.custom')}</small><strong>{editor.name || t('policies.editor.untitled')}</strong></div>{selectedPolicy && <Badge tone={lifecycleTone[selectedPolicy.lifecycle_state]}>{t(`policies.lifecycle.${selectedPolicy.lifecycle_state}`)}</Badge>}</div>
          {selectedPolicy?.lifecycle_state !== 'DRAFT' && <p className="access-callout warning">{t('policies.editor.immutable')}</p>}
          <div className="access-form-grid">
            <label className="field"><span>{t('policies.editor.name')}</span><input value={editor.name} disabled={selectedPolicy?.lifecycle_state !== 'DRAFT' && selection.kind === 'CUSTOM'} onChange={(event) => setEditor((value) => ({ ...value, name: event.target.value }))} /></label>
            <label className="field"><span>{t('policies.editor.description')}</span><textarea value={editor.description} disabled={selectedPolicy?.lifecycle_state !== 'DRAFT' && selection.kind === 'CUSTOM'} onChange={(event) => setEditor((value) => ({ ...value, description: event.target.value }))} /></label>
          </div>
          {!expert ? <section className="policy-simple-editor"><h2>{activeNative ? t(activeNative.audienceKey) : t('policies.audience.roles')}</h2><p>{activeNative ? t(activeNative.helpKey) : t('policies.audience.customHelp')}</p>
            {(activeNative?.editorKind === 'MODE' || activeNative?.editorKind === 'MENTIONS') && <div className="policy-mode-picker" role="radiogroup" aria-label={t(activeNative.audienceKey)}>
              {(['EVERYONE', 'ONLY', 'NONE'] as const).map((mode) => <label key={mode}><input type="radio" name="policy-mode" checked={editor.reactionMode === mode} disabled={editorDisabled} onChange={() => setEditor((value) => ({ ...value, reactionMode: mode }))} /><span>{t(`policies.mode.${mode}`)}</span></label>)}
            </div>}
            {activeNative?.editorKind === 'MENTIONS' && <div className="policy-sensitive-mentions"><label><input type="checkbox" checked={editor.reactionMode !== 'NONE'} disabled={editorDisabled} onChange={(event) => setEditor((value) => ({ ...value, reactionMode: event.target.checked ? 'ONLY' : 'NONE' }))} /><span>{t('policies.mentions.everyone')}</span></label><label><input type="checkbox" checked={editor.reactionMode !== 'NONE'} disabled={editorDisabled} onChange={(event) => setEditor((value) => ({ ...value, reactionMode: event.target.checked ? 'ONLY' : 'NONE' }))} /><span>{t('policies.mentions.here')}</span></label><p>{t('policies.mentions.sharedPermission')}</p><p>{t('policies.mentions.rolesGlobal')}</p></div>}
            {activeNative?.editorKind === 'BOT' && <div className="policy-bot-editor">
              <label className="field"><span>{t('policies.bot.select')}</span><select value={editor.botId} disabled={editorDisabled || botsQuery.isLoading} onChange={(event) => setEditor((value) => ({ ...value, botId: event.target.value }))}><option value="">{t('policies.bot.none')}</option>{(botsQuery.data?.bots ?? []).map((bot) => <option key={bot.user_id} value={bot.user_id}>{t('policies.bot.observed', { id: partialMember(bot.user_id) })}</option>)}</select></label>
              {botsQuery.isError && <p className="access-callout warning">{t('policies.bot.unavailable')}</p>}
              <div className="policy-role-picker" role="group" aria-label={t('policies.bot.functions')}>{(['READ', 'WRITE', 'MANAGE', ...(selectedTarget?.kind === 'VOICE_CHANNEL' ? ['VOCAL'] : ['THREADS'])] as BotFunction[]).map((value) => <label key={value}><input type="checkbox" checked={editor.botFunctions.includes(value)} disabled={editorDisabled} onChange={(event) => setEditor((state) => ({ ...state, botFunctions: event.target.checked ? [...state.botFunctions, value] : state.botFunctions.filter((item) => item !== value) }))} /><span>{t(`policies.bot.function.${value}`)}</span></label>)}</div>
              {botAccessQuery.isLoading && <p>{t('policies.bot.checking')}</p>}{botMinimum && <div className="policy-bot-result"><Badge tone={botMinimum.outcome === 'CAN' ? 'ok' : botMinimum.outcome === 'CANNOT' ? 'danger' : 'warning'}>{t(`policies.outcome.${botMinimum.outcome}`)}</Badge>{botMinimum.outcome === 'CAN' ? <p>{t('policies.bot.sufficient')}</p> : botMinimum.outcome === 'UNKNOWN' ? <><p className="access-callout warning">{t('policies.bot.unknownCause')}</p><p>{t('policies.bot.unknownRemediation')}</p></> : <><p>{t('policies.bot.missing', { permissions: botMinimum.missing_permissions.join(', ') })}</p><p>{t('policies.bot.grantRemediation')}</p></>}<details><summary>{t('policies.expert.discordDetails')}</summary><p><code>{botMinimum.required_permissions.join(', ')}</code></p>{botMinimum.causes.map((cause) => <p key={cause}><code>{cause}</code></p>)}{botMinimum.remediations.map((remediation) => <p key={remediation}><code>{remediation}</code></p>)}</details></div>}
            </div>}
            {activeNative?.editorKind !== 'BOT' && (activeNative?.editorKind === undefined || activeNative.editorKind === 'AUDIENCE' || editor.reactionMode === 'ONLY') && <div className="policy-role-picker" role="group" aria-label={t('policies.audience.roles')}>{roles.map((role) => <label key={role.id}><input type="checkbox" checked={editor.roleIds.includes(role.id)} disabled={editorDisabled} onChange={(event) => setEditor((value) => ({ ...value, roleIds: event.target.checked ? [...value.roleIds, role.id] : value.roleIds.filter((id) => id !== role.id) }))} /><span>{role.name}</span></label>)}</div>}
            {activeNative?.id === 'private_voice' && <div className="policy-staff-option"><label><input type="checkbox" checked={editor.includeStaff} disabled={editorDisabled} onChange={(event) => setEditor((value) => ({ ...value, includeStaff: event.target.checked }))} /><span>{t('policies.voice.staffAlwaysJoin')}</span></label>{editor.includeStaff && <><p className="access-callout warning">{t('policies.voice.staffExplicit')}</p><div className="policy-role-picker">{roles.map((role) => <label key={role.id}><input type="checkbox" checked={editor.staffRoleIds.includes(role.id)} disabled={editorDisabled} onChange={(event) => setEditor((value) => ({ ...value, staffRoleIds: event.target.checked ? [...value.staffRoleIds, role.id] : value.staffRoleIds.filter((id) => id !== role.id) }))} /><span>{role.name}</span></label>)}</div></>}</div>}
            {activeNative?.id === 'open_read_limited_write' && <div className="policy-secondary-options"><label className="field"><span>{t('policies.options.reactions')}</span><select value={editor.reactionMode} disabled={editorDisabled} onChange={(event) => setEditor((value) => ({ ...value, reactionMode: event.target.value as PolicyMode }))}>{(['INHERIT', 'EVERYONE', 'ONLY', 'NONE'] as const).map((mode) => <option key={mode} value={mode}>{t(`policies.mode.${mode}`)}</option>)}</select></label><label className="field"><span>{t('policies.options.threads')}</span><select value={editor.threadMode} disabled={editorDisabled} onChange={(event) => setEditor((value) => ({ ...value, threadMode: event.target.value as PolicyMode }))}>{(['INHERIT', 'EVERYONE', 'ONLY', 'NONE'] as const).map((mode) => <option key={mode} value={mode}>{t(`policies.mode.${mode}`)}</option>)}</select></label></div>}
            <div className="policy-human-result"><strong>{t('policies.result.title')}</strong>{[...new Set(visibleDefinition?.effects.map((effect) => effect.access) ?? [])].map((access) => <span key={access}>{t(`policies.access.${access}`)}</span>)}<p>{activeNative?.audienceMode === 'EXCLUDE' ? t('policies.result.excluded') : t('policies.result.others')}</p></div>
          </section> : <section className="policy-expert-editor"><label className="field"><span>{t('policies.expert.priority')}</span><input type="number" min="-1000000" max="1000000" value={editor.priority} disabled={selectedPolicy?.lifecycle_state !== 'DRAFT' && selection.kind === 'CUSTOM'} onChange={(event) => setEditor((value) => ({ ...value, priority: Number(event.target.value) }))} /></label>
            <dl><div><dt>{t('policies.expert.id')}</dt><dd><code>{selectedPolicy?.policy_id ?? `native:${activeNative?.id}`}</code></dd></div><div><dt>{t('policies.expert.revision')}</dt><dd>{selectedPolicy?.revision ?? 1}</dd></div><div><dt>{t('policies.expert.scope')}</dt><dd><code>{selectedPolicy?.scope_type ?? selectedTarget?.scopeType}:{selectedPolicy?.scope_id ?? selectedTarget?.scopeId ?? '*'}</code></dd></div></dl>
            <h3>{t('policies.expert.conditions')}</h3><pre>{JSON.stringify(visibleDefinition?.conditions ?? [], null, 2)}</pre>
            <h3>{t('policies.expert.effects')}</h3><pre>{JSON.stringify(visibleDefinition?.effects ?? [], null, 2)}</pre>
            <p className="access-help">{t('policies.expert.discordTranslation')}</p>
          </section>}
          <div className="button-row">
            <button type="button" className="button primary" disabled={busy || !canSave} title={!canSave ? t('policies.error.editDenied') : undefined} onClick={() => void save()}>{selection.kind === 'NATIVE' ? t('policies.createDraft') : t('policies.saveDraft')}</button>
            {selectedPolicy && <button type="button" className="button quiet" disabled={busy || canCreate !== 'CAN'} onClick={() => void duplicate(selectedPolicy)}>{t('policies.duplicate')}</button>}
            {selectedPolicy && <button type="button" className="button quiet" onClick={() => setHistoryOpen((value) => !value)}>{t('policies.history')}</button>}
          </div>
          {selectedPolicy?.lifecycle_state === 'DRAFT' && <div className="draft-safety"><Badge tone="warning">{t('policies.lifecycle.DRAFT')}</Badge><span>{t('policies.draft.safety')}</span></div>}
        </>}
        {problem && <p className="access-callout danger" role="alert">{problem}</p>}{notice && <p className="access-callout success" role="status">{notice}</p>}
      </article>
    </div>

    {historyOpen && selectedPolicy && <article className="access-panel policy-history-panel"><div className="access-panel-heading"><div><small>{selectedPolicy.name}</small><strong>{t('policies.history.title')}</strong></div></div>
      {versionsQuery.isLoading ? <Skeleton /> : versionsQuery.isError ? <ErrorState retry={() => void versionsQuery.refetch()} /> : <ol>{(versionsQuery.data?.versions ?? []).map((version) => <li key={version.version_id}><div><strong>{t('policies.revision', { revision: version.revision })}</strong><span>{new Intl.DateTimeFormat(i18n.language, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(version.created_at))}</span><small>{t(`policies.change.${version.change_kind}`, { kind: version.change_kind })} · {t('policies.history.author', { author: partialMember(version.author_user_id) })}</small></div><button type="button" className="button quiet" disabled={busy || canCreate !== 'CAN'} onClick={() => void draftFromVersion(version)}>{t('policies.history.createDraft')}</button></li>)}</ol>}
      <p className="access-help">{t('policies.history.safety')}</p>
    </article>}

    {selectedPolicy?.lifecycle_state === 'DRAFT' && <article className="access-panel policy-preview-panel"><div className="access-panel-heading"><div><small>{t('policies.step.preview')}</small><strong>{t('policies.preview.title')}</strong></div>{preview && <Badge tone={preview.impact.accuracy === 'EXACT' ? 'ok' : 'warning'}>{t(`policies.accuracy.${preview.impact.accuracy}`)}</Badge>}</div>
      {!preview ? <div className="policy-preview-empty"><p>{t('policies.preview.help')}</p><button type="button" className="button primary" disabled={busy} onClick={() => void loadPreview()}>{t('policies.preview.action')}</button></div> : <>
        <div className="policy-impact-grid"><div><strong>{preview.impact.access_gains}</strong><span>{t('policies.impact.gains')}</span></div><div><strong>{preview.impact.access_losses}</strong><span>{t('policies.impact.losses')}</span></div><div><strong>{preview.impact.affected_members}</strong><span>{t('policies.impact.members')}</span></div><div><strong>{preview.impact.affected_roles}</strong><span>{t('policies.impact.roles')}</span></div><div><strong>{preview.impact.affected_resources}</strong><span>{t('policies.impact.resources')}</span></div><div><strong>{preview.impact.conflicts}</strong><span>{t('policies.impact.conflicts')}</span></div></div>
        {preview.impact.diagnostics.map((diagnostic) => <p className="access-callout warning" key={diagnostic}>{t(`policies.diagnostic.${diagnostic}`, { diagnostic })}</p>)}
        <div className="policy-preview-entries">{preview.entries.map((entry, index) => <article key={`${entry.target.subject_id}-${entry.target.scope_id}-${entry.target.requested_access}-${index}`} className={entry.proposed.outcome === 'BLOCKED' || entry.proposed.outcome === 'UNKNOWN' ? 'problem' : ''}>
          <div className="policy-entry-heading"><div><strong>{t('policies.member.partial', { suffix: partialMember(entry.target.subject_id) })}</strong><small>{t(`policies.access.${entry.target.requested_access}`)}</small></div><Badge tone={entry.proposed.outcome === 'CAN' ? 'ok' : entry.proposed.outcome === 'CANNOT' ? 'danger' : 'warning'}>{t(`policies.outcome.${entry.proposed.outcome}`)}</Badge></div>
          <p>{t('policies.preview.change', { before: t(`policies.outcome.${entry.current.outcome}`), after: t(`policies.outcome.${entry.proposed.outcome}`) })}</p>
          {[...new Set([...entry.proposed.incomplete_reasons, ...entry.diagnostics])].map((reason) => <p className="access-callout warning" key={reason}>{t('policies.reason', { reason })}</p>)}
          {entry.proposed.conflicts.map((conflict, conflictIndex) => <div className="policy-conflict" key={`${conflict.policy_ids.join('-')}-${conflictIndex}`}><strong>{t('policies.conflict.member', { member: partialMember(entry.target.subject_id) })}</strong><p>{t('policies.conflict.sources', { sources: conflict.policy_ids.map(policyName).join(' / '), effects: conflict.effects.join(' / ') })}</p><p>{conflict.outcome === 'RESOLVED' ? t('policies.conflict.winner', { winner: conflict.winning_policy_ids.map(policyName).join(', '), rule: conflict.resolution_rule ?? '—' }) : t('policies.conflict.blocked')}</p><button type="button" className="button quiet" onClick={() => setRemediationKey(remediationKey === `${index}:${conflictIndex}` ? null : `${index}:${conflictIndex}`)}>{t('policies.conflict.resolve')}</button>{remediationKey === `${index}:${conflictIndex}` && <ul><li>{t('policies.conflict.option.keep')}</li><li>{t('policies.conflict.option.priority')}</li><li>{t('policies.conflict.option.draft')}</li></ul>}</div>)}
          <button type="button" className="button quiet" disabled={busy} onClick={() => void explain(entry)}>{t('policies.explain.action')}</button>
          <details><summary>{t('policies.expert.discordDetails')}</summary><p>{entry.proposed.discord_permissions.join(', ') || '—'}</p><code>allow={entry.proposed.discord_allow_bits} · deny={entry.proposed.discord_deny_bits}</code>{entry.proposed.discord_translation_diagnostics.map((diagnostic) => <p className="access-callout warning" key={diagnostic}>{t('policies.reason', { reason: diagnostic })}</p>)}</details>
          {expert && <details><summary>{t('policies.expert.resolution')}</summary><pre>{JSON.stringify(entry.proposed, null, 2)}</pre></details>}
        </article>)}</div>
        {blocker && <p className="access-callout danger">{blocker}</p>}
        <div className="button-row"><button type="button" className="button primary" disabled={busy || Boolean(blocker)} title={blocker ?? undefined} onClick={() => void preparePlan()}>{t('policies.plan.prepare')}</button></div>
      </>}
    </article>}

    {explanation && <article className="access-panel policy-explain-panel"><div className="access-panel-heading"><div><small>{t('policies.explain.question')}</small><strong>{t(`policies.outcome.${explanation.outcome}`)}</strong></div></div>
      <dl><div><dt>{t('policies.explain.allowedBy')}</dt><dd>{explanation.contributions.filter((item) => item.selected).map((item) => policyName(item.policy_id)).join(', ') || t('policies.explain.none')}</dd></div><div><dt>{t('policies.explain.inherited')}</dt><dd>{explanation.source_scopes.filter((item) => item.inherited).map((item) => policyName(item.policy_id)).join(', ') || t('policies.explain.none')}</dd></div><div><dt>{t('policies.explain.exception')}</dt><dd>{explanation.conflicts.length ? t('policies.conflicts.count', { count: explanation.conflicts.length }) : t('policies.explain.none')}</dd></div></dl>
      {explanation.incomplete_reasons.map((reason) => <p className="access-callout warning" key={reason}>{t('policies.reason', { reason })}</p>)}
      <details><summary>{t('policies.expert.discordDetails')}</summary><p>{explanation.discord_permissions.join(', ') || '—'}</p><code>allow={explanation.discord_allow_bits} · deny={explanation.discord_deny_bits}</code></details>
      {expert && <pre>{JSON.stringify(explanation, null, 2)}</pre>}
    </article>}
  </section>
}

export { nativePolicies }
