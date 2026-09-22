import { useEffect, useMemo, useRef, useState } from 'react'
import { TextInput } from '@mantine/core'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Bot, Check, ChevronRight, Eye, MessageCircle, Mic2, Search, ShieldCheck, Star, UsersRound, X, type LucideIcon } from 'lucide-react'
import { useNavigate, useOutletContext, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { apiRequest } from '../../api/client'
import { usePolicies, usePolicyFavorites, useRoles, useStructure } from '../../api/queries'
import type { CapabilityOutcome, LogicalGroup, Policy, PolicyAccess, PolicyDeletionPreview, PolicyDeletionStrategy, PolicyFavorites, PolicyPreview, PolicyPreviewEntry, PolicyResolution, PolicyTemporaryAccess, PolicyVersion, Role } from '../../api/types'
import type { DashboardContext } from '../../app/AppShell'
import { Badge, ErrorState, Skeleton } from '../../shared/components/ui'
import { apiProblem } from './errors'
import { findNamedAudience, suggestStaffRoleIds, useSaveNamedAudience, useVisibilityScopes, type NamedAudience } from './audiences'
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
import { findPairedZones, useCreatePairedZone, zoneResourceLabel } from './zones'
import {
  announcementSubRules, compatiblePresets, confidentialSubRules, createAnnouncementDefinitions, createConfidentialDefinitions,
  createSupportZoneDefinitions, emptyAnnouncementConfig, emptyConfidentialConfig, emptySupportZoneConfig, supportZoneSubRules,
  type AnnouncementConfig, type ConfidentialConfig, type PresetId, type SupportZoneConfig,
} from './presets'

type Selection = { kind: 'NATIVE'; native: NativePolicy } | { kind: 'CUSTOM'; policy: Policy }
type EditorState = {
  name: string; description: string; priority: number; roleIds: string[]
  reactionMode: PolicyMode; threadMode: PolicyMode; replyMode: PolicyMode; includeStaff: boolean; staffRoleIds: string[]
  botId: string; botFunctions: BotFunction[]
  excludedRoleIds: string[]
}
type BotAudit = { user_id: string; status: string; incomplete_reasons: string[] }
type BotMinimum = {
  functions: BotFunction[]; outcome: CapabilityOutcome; required_permissions: string[]
  missing_permissions: string[]; causes: string[]; remediations: string[]; warnings: string[]
}
type BotAccessMap = { channels: Array<{ channel_id: string; status: string; minimum?: BotMinimum }> }

const emptyEditor = (): EditorState => ({
  name: '', description: '', priority: 0, roleIds: [], reactionMode: 'ONLY',
  threadMode: 'INHERIT', replyMode: 'INHERIT', includeStaff: false, staffRoleIds: [], botId: '', botFunctions: [],
  excludedRoleIds: [],
})

const lifecycleTone = { DRAFT: 'warning', ACTIVE: 'ok', DISABLED: 'neutral', RETIRED: 'danger' } as const

const familyIcons: Record<NativePolicy['family'], LucideIcon> = {
  VISIBILITY: Eye,
  WRITING: MessageCircle,
  AUDIENCE: UsersRound,
  ZONE: ShieldCheck,
  VOCAL: Mic2,
  THREADS: MessageCircle,
  REACTIONS: Star,
  MENTIONS: UsersRound,
  BOTS: Bot,
}

function policyIcon(native: NativePolicy): LucideIcon {
  if (native.editorKind === 'BOT') return Bot
  if (native.compatibility.includes('VOICE_CHANNEL')) return Mic2
  return familyIcons[native.family]
}

type RoleChipPickerProps = {
  label: string
  roles: readonly Role[]
  selected: readonly string[]
  disabled?: boolean
  searchLabel: string
  selectedLabel: string
  moreLabel: string
  lessLabel: string
  emptyLabel: string
  onChange: (roleIds: string[]) => void
}

function RoleChipPicker({ label, roles, selected, disabled = false, searchLabel, selectedLabel, moreLabel, lessLabel, emptyLabel, onChange }: RoleChipPickerProps) {
  const [query, setQuery] = useState('')
  const [expanded, setExpanded] = useState(false)
  const normalizedQuery = query.trim().toLocaleLowerCase()
  const matches = roles.filter((role) => role.name.toLocaleLowerCase().includes(normalizedQuery))
  const visible = normalizedQuery || expanded ? matches : matches.slice(0, 8)
  const selectedRoles = selected.map((id) => roles.find((role) => role.id === id)).filter((role): role is Role => Boolean(role))
  const toggle = (roleId: string, checked: boolean) => onChange(checked ? [...selected, roleId] : selected.filter((id) => id !== roleId))

  return <div className="policy-role-selector" role="group" aria-label={label}>
    <div className="policy-role-selector-heading"><strong>{label}</strong><span>{selected.length}</span></div>
    {selectedRoles.length > 0 && <div className="policy-selected-roles" aria-label={selectedLabel}>
      {selectedRoles.map((role) => <button type="button" key={role.id} disabled={disabled} onClick={() => toggle(role.id, false)}><Check size={13} /><span>{role.name}</span><X size={12} aria-hidden="true" /></button>)}
    </div>}
    <TextInput value={query} onChange={(event) => setQuery(event.currentTarget.value)} placeholder={searchLabel} aria-label={`${searchLabel} — ${label}`} leftSection={<Search size={15} />} disabled={disabled} />
    <div className="policy-role-options">
      {visible.map((role) => <label key={role.id} className={selected.includes(role.id) ? 'selected' : ''}><input type="checkbox" checked={selected.includes(role.id)} disabled={disabled} onChange={(event) => toggle(role.id, event.target.checked)} /><span>{role.name}</span>{selected.includes(role.id) && <Check size={15} aria-hidden="true" />}</label>)}
      {visible.length === 0 && <p>{emptyLabel}</p>}
    </div>
    {!normalizedQuery && matches.length > 8 && <button type="button" className="policy-role-more" disabled={disabled} onClick={() => setExpanded((value) => !value)}>{expanded ? lessLabel : moreLabel}</button>}
  </div>
}

function localDateTimeInput(value: Date): string {
  return new Date(value.getTime() - value.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
}

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
    replyMode: modeFromPolicy(policy, 'PARTICIPATE_THREAD'),
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
  const [searchParams] = useSearchParams()
  const client = useQueryClient()
  const canRead = capabilities?.user_capabilities['policies.read']?.outcome ?? 'UNKNOWN'
  const canCreate = capabilities?.user_capabilities['policies.create']?.outcome ?? 'UNKNOWN'
  const canUpdate = capabilities?.user_capabilities['policies.update']?.outcome ?? 'UNKNOWN'
  const canRetire = capabilities?.user_capabilities['policies.retire']?.outcome ?? 'UNKNOWN'
  const canActivate = capabilities?.user_capabilities['policies.activate']?.outcome === 'CAN'
  const canPrepare = canActivate
    && capabilities?.user_capabilities['plans.create']?.outcome === 'CAN'
  const policyWorkspaceEnabled = canRead === 'CAN'
  const policiesQuery = usePolicies(me.user.discord_user_id, guild.guild_id, policyWorkspaceEnabled)
  const favoritesQuery = usePolicyFavorites(me.user.discord_user_id, guild.guild_id, policyWorkspaceEnabled)
  const rolesQuery = useRoles(me.user.discord_user_id, guild.guild_id, policyWorkspaceEnabled)
  const structureQuery = useStructure(me.user.discord_user_id, guild.guild_id, false, policyWorkspaceEnabled)
  const groupsQuery = useQuery({
    enabled: policyWorkspaceEnabled,
    queryKey: ['did', me.user.discord_user_id, guild.guild_id, 'logical-groups'],
    queryFn: () => apiRequest<{groups:LogicalGroup[]}>(`/api/v1/guilds/${guild.guild_id}/logical-groups`),
  })
  const visibilityScopesQuery = useVisibilityScopes(me.user.discord_user_id, guild.guild_id, policyWorkspaceEnabled)
  const saveNamedAudience = useSaveNamedAudience(me.user.discord_user_id, guild.guild_id)
  const createPairedZone = useCreatePairedZone(me.user.discord_user_id, guild.guild_id)
  const [zoneFormOpen, setZoneFormOpen] = useState(false)
  const [zoneName, setZoneName] = useState('')
  const [zonePublicValue, setZonePublicValue] = useState('')
  const [zoneStaffValue, setZoneStaffValue] = useState('')
  const [zoneBusy, setZoneBusy] = useState(false)
  const [zoneProblem, setZoneProblem] = useState<string | null>(null)
  const [presetOpen, setPresetOpen] = useState<PresetId | null>(null)
  const [presetName, setPresetName] = useState('')
  const [presetDescription, setPresetDescription] = useState('')
  const [confidentialConfig, setConfidentialConfig] = useState<ConfidentialConfig>(emptyConfidentialConfig)
  const [announcementConfig, setAnnouncementConfig] = useState<AnnouncementConfig>(emptyAnnouncementConfig)
  const [supportZoneConfig, setSupportZoneConfig] = useState<SupportZoneConfig>(emptySupportZoneConfig)
  const [presetBusy, setPresetBusy] = useState(false)
  const [presetProblem, setPresetProblem] = useState<string | null>(null)
  const [presetNotice, setPresetNotice] = useState<string | null>(null)
  const [reapplyOpen, setReapplyOpen] = useState(false)
  const [reapplyPreview, setReapplyPreview] = useState<PolicyPreview | null>(null)
  const [reapplyPlan, setReapplyPlan] = useState<{ id: string; status: string } | null>(null)
  const [reapplyBusy, setReapplyBusy] = useState(false)
  const [reapplyProblem, setReapplyProblem] = useState<string | null>(null)
  const [reapplyNotice, setReapplyNotice] = useState<string | null>(null)
  const [audienceEditorOpen, setAudienceEditorOpen] = useState(false)
  const [audienceDraftRoleIds, setAudienceDraftRoleIds] = useState<string[]>([])
  const [audienceBusy, setAudienceBusy] = useState(false)
  const [intentSearch, setIntentSearch] = useState('')
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
  const [driftBusy, setDriftBusy] = useState(false)
  const [driftProblem, setDriftProblem] = useState<string | null>(null)
  const [driftNotice, setDriftNotice] = useState<string | null>(null)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deletionPreview, setDeletionPreview] = useState<PolicyDeletionPreview | null>(null)
  const [deletionStrategy, setDeletionStrategy] = useState<PolicyDeletionStrategy>('DETACH')
  const [replacementPolicyId, setReplacementPolicyId] = useState('')
  const [deleteBusy, setDeleteBusy] = useState(false)
  const [deleteProblem, setDeleteProblem] = useState<string | null>(null)
  const [favoriteBusy, setFavoriteBusy] = useState<string | null>(null)
  const [favoriteProblem, setFavoriteProblem] = useState<string | null>(null)
  const [temporaryUntil, setTemporaryUntil] = useState(() => localDateTimeInput(new Date(Date.now() + 24 * 60 * 60 * 1000)))
  const [temporaryBusy, setTemporaryBusy] = useState(false)
  const [temporaryProblem, setTemporaryProblem] = useState<string | null>(null)
  const deleteDialogRef = useRef<HTMLDialogElement>(null)
  const appliedTargetRequest = useRef<string | null>(null)

  useEffect(() => {
    const dialog = deleteDialogRef.current
    if (!dialog) return
    if (deleteOpen && !dialog.open) dialog.showModal()
    if (!deleteOpen && dialog.open) dialog.close()
  }, [deleteOpen])

  const roles = useMemo(() => [...(rolesQuery.data?.roles ?? [])].filter((role) => !role.managed).sort((a, b) => b.position - a.position), [rolesQuery.data])
  const targets = useMemo<PolicyTarget[]>(
    () => buildPolicyTargets(guild, roles, groupsQuery.data?.groups, structureQuery.data),
    [groupsQuery.data, guild, roles, structureQuery.data],
  )
  const requestedTargetType = searchParams.get('targetType')
  const requestedTargetId = searchParams.get('targetId')
  const requestedTarget = requestedTargetType && requestedTargetId
    ? targets.find((target) => target.scopeType === requestedTargetType && target.scopeId === requestedTargetId)
    : undefined
  useEffect(() => {
    if (!requestedTarget) return
    const requestKey = `${guild.guild_id}:${requestedTarget.scopeType}:${requestedTarget.scopeId}`
    if (appliedTargetRequest.current === requestKey) return
    appliedTargetRequest.current = requestKey
    setTargetValue(targetKey(requestedTarget))
    setSelection(null); setPreview(null); setExplanation(null)
  }, [guild.guild_id, requestedTarget])
  const selectedTarget = targets.find((target) => targetKey(target) === targetValue) ?? targets[0] ?? null
  const zoneableTargets = useMemo(() => targets.filter((target) => target.kind === 'CATEGORY' || target.kind === 'TEXT_CHANNEL' || target.kind === 'VOICE_CHANNEL'), [targets])
  const pairedZones = useMemo(() => findPairedZones(groupsQuery.data?.groups ?? []), [groupsQuery.data])
  const availablePresets = useMemo(() => compatiblePresets(selectedTarget?.kind ?? null), [selectedTarget])
  const presetSubRules = presetOpen === 'confidential' ? confidentialSubRules(confidentialConfig)
    : presetOpen === 'announcement_channel' ? announcementSubRules(announcementConfig)
      : presetOpen === 'support_zone' ? supportZoneSubRules(supportZoneConfig)
        : []
  const announcementNeedsPublishers = presetOpen === 'announcement_channel' && announcementConfig.publisherRoleIds.length === 0
    && [announcementConfig.reactionMode, announcementConfig.threadMode, announcementConfig.replyMode].includes('ONLY')
  function roleNames(roleIds: readonly string[] | undefined): string {
    if (!roleIds?.length) return ''
    return roleIds.map((id) => roles.find((role) => role.id === id)?.name ?? id).join(', ')
  }

  function rolePicker(labelKey: string, selected: readonly string[], onChange: (roleIds: string[]) => void, disabled = false) {
    return <RoleChipPicker
      label={t(labelKey)}
      roles={roles}
      selected={selected}
      disabled={disabled}
      searchLabel={t('policies.roles.search')}
      selectedLabel={t('policies.roles.selected')}
      moreLabel={t('policies.roles.more')}
      lessLabel={t('policies.roles.less')}
      emptyLabel={t('policies.roles.empty')}
      onChange={onChange}
    />
  }

  function presetRolePicker(labelKey: string, selected: readonly string[], onChange: (roleIds: string[]) => void) {
    return rolePicker(labelKey, selected, onChange)
  }
  const channelTypes = useMemo(() => new Map(targets.filter((target) => target.scopeType === 'CHANNEL' && target.scopeId).map((target) => [target.scopeId as string, target.kind === 'VOICE_CHANNEL' ? 2 : 0])), [targets])
  const customPolicies = (policiesQuery.data?.policies ?? []).filter((policy) => isPolicyCompatible(policy, selectedTarget, channelTypes))
  const availableNatives = compatibleNativePolicies(selectedTarget?.kind ?? null)
  const favoriteKeys = new Set(favoritesQuery.data?.favorite_keys ?? [])
  const favoriteNatives = availableNatives.filter((native) => favoriteKeys.has(`native:${native.id}`))
  const favoriteCustomPolicies = customPolicies.filter((policy) => favoriteKeys.has(`custom:${policy.policy_id}`))
  const otherNatives = availableNatives.filter((native) => !favoriteKeys.has(`native:${native.id}`))
  const otherCustomPolicies = customPolicies.filter((policy) => !favoriteKeys.has(`custom:${policy.policy_id}`))
  const normalizedIntentSearch = intentSearch.trim().toLocaleLowerCase()
  const nativeMatches = (native: NativePolicy) => `${t(native.titleKey)} ${t(native.summaryKey)}`.toLocaleLowerCase().includes(normalizedIntentSearch)
  const customMatches = (policy: Policy) => `${policy.name} ${policy.metadata.summary}`.toLocaleLowerCase().includes(normalizedIntentSearch)
  const visibleFavoriteNatives = favoriteNatives.filter(nativeMatches)
  const visibleFavoriteCustomPolicies = favoriteCustomPolicies.filter(customMatches)
  const visibleOtherNatives = otherNatives.filter(nativeMatches)
  const visibleOtherCustomPolicies = otherCustomPolicies.filter(customMatches)
  const selectedPolicy = selection?.kind === 'CUSTOM' ? selection.policy : null
  const activeNative = selection?.kind === 'NATIVE' ? selection.native : selectedPolicy ? nativePolicyByTag(selectedPolicy) : undefined
  const parentCategoryId = selectedPolicy?.scope_type === 'CHANNEL'
    ? structureQuery.data?.categories.find((category) => category.channels.some((channel) => channel.id === selectedPolicy.scope_id))?.id ?? null
    : null
  const canReapplyCategoryPolicy = Boolean(
    selectedPolicy && selectedPolicy.lifecycle_state === 'ACTIVE' && parentCategoryId
    && (policiesQuery.data?.policies ?? []).some((policy) => policy.lifecycle_state === 'ACTIVE' && policy.scope_type === 'CATEGORY' && policy.scope_id === parentCategoryId),
  )
  const scopes = visibilityScopesQuery.data?.scopes ?? []
  const existingAudienceScope = activeNative?.requiresNamedAudience
    ? scopes.find((scope) => (activeNative.requiresNamedAudience === 'STAFF' ? scope.scope_type === 'STAFF' : scope.scope_type === 'CUSTOM' && scope.scope_key === 'confirmed_member'))
    : undefined
  const namedAudience: NamedAudience | null = activeNative?.requiresNamedAudience ? findNamedAudience(scopes, activeNative.requiresNamedAudience) : null
  const staffSuggestion = activeNative?.requiresNamedAudience === 'STAFF' && !namedAudience ? suggestStaffRoleIds(roles) : []
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
  const driftQuery = useQuery({
    enabled: Boolean(selectedPolicy?.lifecycle_state === 'ACTIVE'),
    queryKey: ['did', me.user.discord_user_id, guild.guild_id, 'policies', selectedPolicy?.policy_id ?? 'none', 'drift', selectedPolicy?.revision ?? 0],
    queryFn: () => apiRequest<PolicyPreview>(`/api/v1/guilds/${guild.guild_id}/policies/${selectedPolicy?.policy_id}/drift-preview`, { method: 'POST' }),
  })
  const temporaryQuery = useQuery({
    enabled: Boolean(selectedPolicy?.lifecycle_state === 'ACTIVE'),
    queryKey: ['did', me.user.discord_user_id, guild.guild_id, 'policies', selectedPolicy?.policy_id ?? 'none', 'temporary-access'],
    queryFn: () => apiRequest<{ temporary_access: PolicyTemporaryAccess | null }>(`/api/v1/guilds/${guild.guild_id}/policies/${selectedPolicy?.policy_id}/temporary-access`),
  })

  function chooseNative(native: NativePolicy) {
    setSelection({ kind: 'NATIVE', native })
    const audienceRoleIds = native.requiresNamedAudience ? findNamedAudience(visibilityScopesQuery.data?.scopes ?? [], native.requiresNamedAudience)?.roleIds ?? [] : []
    setEditor({ ...emptyEditor(), name: t(native.titleKey), description: t(native.summaryKey), botFunctions: native.id === 'bot_minimal' ? ['READ'] : [], roleIds: [...audienceRoleIds] })
    setAudienceEditorOpen(false)
    setPreview(null); setExplanation(null); setProblem(null); setNotice(null); setHistoryOpen(false)
    setDriftProblem(null); setDriftNotice(null)
    resetReapply()
  }

  async function createPairedZoneFromForm() {
    const publicTarget = zoneableTargets.find((target) => targetKey(target) === zonePublicValue)
    const staffTarget = zoneableTargets.find((target) => targetKey(target) === zoneStaffValue)
    if (!zoneName.trim() || !publicTarget || !staffTarget || publicTarget === staffTarget) return
    setZoneBusy(true); setZoneProblem(null)
    try {
      await createPairedZone(zoneName.trim(), publicTarget, staffTarget)
      setZoneName(''); setZonePublicValue(''); setZoneStaffValue(''); setZoneFormOpen(false)
    } catch (error) { setZoneProblem(apiProblem(error, t)) }
    finally { setZoneBusy(false) }
  }

  async function scheduleTemporaryAccess(hours?: number) {
    if (!selectedPolicy) return
    const expiresAt = hours === undefined ? new Date(temporaryUntil) : new Date(Date.now() + hours * 60 * 60 * 1000)
    if (Number.isNaN(expiresAt.getTime())) return
    setTemporaryBusy(true); setTemporaryProblem(null)
    try {
      const result = await apiRequest<{ temporary_access: PolicyTemporaryAccess }>(`/api/v1/guilds/${guild.guild_id}/policies/${selectedPolicy.policy_id}/temporary-access`, { method: 'PUT', body: { expires_at: expiresAt.toISOString() } })
      client.setQueryData(['did', me.user.discord_user_id, guild.guild_id, 'policies', selectedPolicy.policy_id, 'temporary-access'], result)
      setTemporaryUntil(localDateTimeInput(expiresAt))
    } catch (error) { setTemporaryProblem(apiProblem(error, t)) }
    finally { setTemporaryBusy(false) }
  }

  async function cancelTemporaryAccess() {
    if (!selectedPolicy) return
    setTemporaryBusy(true); setTemporaryProblem(null)
    try {
      const result = await apiRequest<{ temporary_access: PolicyTemporaryAccess }>(`/api/v1/guilds/${guild.guild_id}/policies/${selectedPolicy.policy_id}/temporary-access`, { method: 'DELETE' })
      client.setQueryData(['did', me.user.discord_user_id, guild.guild_id, 'policies', selectedPolicy.policy_id, 'temporary-access'], result)
    } catch (error) { setTemporaryProblem(apiProblem(error, t)) }
    finally { setTemporaryBusy(false) }
  }

  function resetPresetForm() {
    setPresetOpen(null); setPresetName(''); setPresetDescription(''); setPresetProblem(null)
    setConfidentialConfig(emptyConfidentialConfig()); setAnnouncementConfig(emptyAnnouncementConfig()); setSupportZoneConfig(emptySupportZoneConfig())
  }

  async function createPresetDrafts() {
    if (!selectedTarget || !presetOpen || !presetName.trim()) return
    const definitions = presetOpen === 'confidential' ? createConfidentialDefinitions(selectedTarget, presetName, presetDescription, confidentialConfig)
      : presetOpen === 'announcement_channel' ? createAnnouncementDefinitions(selectedTarget, presetName, presetDescription, announcementConfig)
        : createSupportZoneDefinitions(selectedTarget, presetName, presetDescription, supportZoneConfig)
    if (definitions.length === 0) return
    setPresetBusy(true); setPresetProblem(null); setPresetNotice(null)
    try {
      for (const definition of definitions) {
        await apiRequest<Policy>(`/api/v1/guilds/${guild.guild_id}/policies`, { method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() }, body: definition })
      }
      await client.invalidateQueries({ queryKey: ['did', me.user.discord_user_id, guild.guild_id, 'policies'] })
      setPresetNotice(t('policies.preset.created', { count: definitions.length }))
      resetPresetForm()
    } catch (error) { setPresetProblem(apiProblem(error, t)) }
    finally { setPresetBusy(false) }
  }

  function configureStaffForZone(staffResourceId: string) {
    const target = targets.find((item) => item.scopeId === staffResourceId)
    const staffNative = nativePolicies.find((native) => native.id === 'staff_only')
    if (!target || !staffNative) return
    setTargetValue(targetKey(target))
    chooseNative(staffNative)
  }

  function chooseCustom(policy: Policy) {
    const target = targets.find((item) => item.scopeType === policy.scope_type && item.scopeId === policy.scope_id)
    if (target) setTargetValue(targetKey(target))
    setSelection({ kind: 'CUSTOM', policy })
    setEditor(editorFromPolicy(policy))
    setPreview(null); setExplanation(null); setProblem(null); setNotice(null); setHistoryOpen(false)
    setDriftProblem(null); setDriftNotice(null)
    resetReapply()
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
    if (activeNative?.editorKind === 'NAMED_AUDIENCE' && editor.roleIds.length === 0) {
      setProblem(t(activeNative.requiresNamedAudience === 'STAFF' ? 'policies.audience.staffConfigRequired' : 'policies.audience.confirmedConfigRequired'))
      return
    }
    const modeNeedsAudience = ['reactions', 'mentions'].includes(activeNative?.id ?? '') && editor.reactionMode === 'ONLY'
    const requiresAudience = activeNative?.editorKind !== 'BOT' && activeNative?.editorKind !== 'NAMED_AUDIENCE'
      && (activeNative?.editorKind === 'AUDIENCE' || activeNative?.editorKind === 'ROLE_BUT_NOT' || !activeNative?.editorKind || modeNeedsAudience
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

  async function openDeletion() {
    if (!selectedPolicy) return
    setDeleteOpen(true); setDeletionPreview(null); setDeletionStrategy('DETACH'); setReplacementPolicyId(''); setDeleteProblem(null); setDeleteBusy(true)
    try {
      const result = await apiRequest<PolicyDeletionPreview>(`/api/v1/guilds/${guild.guild_id}/policies/${selectedPolicy.policy_id}/deletion-preview`, { method: 'POST', body: {} })
      setDeletionPreview(result)
    } catch (error) { setDeleteProblem(apiProblem(error, t)) }
    finally { setDeleteBusy(false) }
  }

  function closeDeletion() {
    setDeleteOpen(false); setDeletionPreview(null); setReplacementPolicyId(''); setDeleteProblem(null)
  }

  async function confirmDeletion() {
    if (!selectedPolicy || !deletionPreview) return
    const selectedStrategy = deletionPreview.strategies.find((value) => value.strategy === deletionStrategy)
    if (!selectedStrategy?.available || (deletionStrategy === 'REPLACE' && !replacementPolicyId)) return
    setDeleteBusy(true); setDeleteProblem(null)
    try {
      let planId: string | null = null
      if (selectedStrategy.requires_plan) {
        if (deletionPreview.access_impact?.impact.accuracy !== 'EXACT') {
          setDeleteProblem(t('policies.delete.exactRequired')); return
        }
        const planned = await apiRequest<{plan:{id:string};preflight:{allowed:boolean;errors:string[]}}>(`/api/v1/guilds/${guild.guild_id}/policies/${selectedPolicy.policy_id}/disable-plan`, {
          method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() }, body: { expected_revision: selectedPolicy.revision },
        })
        if (!planned.preflight.allowed) { setDeleteProblem(t('policies.delete.planBlocked', { reason: planned.preflight.errors.join(', ') || '—' })); return }
        planId = planned.plan.id
      }
      const deleted = await apiRequest<Policy>(`/api/v1/guilds/${guild.guild_id}/policies/${selectedPolicy.policy_id}/delete`, {
        method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() },
        body: { expected_revision: selectedPolicy.revision, strategy: deletionStrategy, replacement_policy_id: deletionStrategy === 'REPLACE' ? replacementPolicyId : null, plan_id: planId },
      })
      await client.invalidateQueries({ queryKey: ['did', me.user.discord_user_id, guild.guild_id, 'policies'] })
      chooseCustom(deleted); closeDeletion(); setNotice(t('policies.delete.done'))
      if (planId) navigate(`/guild/${guild.guild_id}/plans`)
    } catch (error) { setDeleteProblem(apiProblem(error, t)) }
    finally { setDeleteBusy(false) }
  }

  function resetReapply() {
    setReapplyOpen(false); setReapplyPreview(null); setReapplyPlan(null); setReapplyProblem(null); setReapplyNotice(null)
  }

  async function loadReapplyPreview() {
    if (!selectedPolicy) return
    setReapplyBusy(true); setReapplyProblem(null); setReapplyPlan(null)
    try {
      const result = await apiRequest<PolicyPreview>(`/api/v1/guilds/${guild.guild_id}/policies/${selectedPolicy.policy_id}/disable-preview`, { method: 'POST' })
      setReapplyPreview(result)
    } catch (error) { setReapplyProblem(apiProblem(error, t)) }
    finally { setReapplyBusy(false) }
  }

  async function prepareReapplyPlan() {
    if (!selectedPolicy || !reapplyPreview) return
    setReapplyBusy(true); setReapplyProblem(null)
    try {
      const result = await apiRequest<{ plan: { id: string; status: string } }>(`/api/v1/guilds/${guild.guild_id}/policies/${selectedPolicy.policy_id}/disable-plan`, {
        method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() }, body: { expected_revision: selectedPolicy.revision },
      })
      setReapplyPlan(result.plan)
    } catch (error) { setReapplyProblem(apiProblem(error, t)) }
    finally { setReapplyBusy(false) }
  }

  async function confirmReapply() {
    if (!selectedPolicy || !reapplyPlan) return
    setReapplyBusy(true); setReapplyProblem(null)
    try {
      await apiRequest(`/api/v1/guilds/${guild.guild_id}/policies/${selectedPolicy.policy_id}/disable`, {
        method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() },
        body: { expected_revision: selectedPolicy.revision, plan_id: reapplyPlan.id },
      })
      await client.invalidateQueries({ queryKey: ['did', me.user.discord_user_id, guild.guild_id, 'policies'] })
      resetReapply()
      setReapplyNotice(t('policies.reapply.done'))
    } catch (error) { setReapplyProblem(apiProblem(error, t)) }
    finally { setReapplyBusy(false) }
  }

  function policyName(id: string): string {
    return policiesQuery.data?.policies.find((policy) => policy.policy_id === id)?.name ?? t('policies.source.unknown')
  }

  async function acceptException(excludingPolicyId: string, regrantingPolicyId: string) {
    const target = policiesQuery.data?.policies.find((policy) => policy.policy_id === excludingPolicyId)
    if (!target) return
    setBusy(true); setProblem(null)
    try {
      await apiRequest(`/api/v1/guilds/${guild.guild_id}/policies/${excludingPolicyId}/accept-exception`, {
        method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() },
        body: { expected_revision: target.revision, other_policy_id: regrantingPolicyId },
      })
      await client.invalidateQueries({ queryKey: ['did', me.user.discord_user_id, guild.guild_id, 'policies'] })
      if (explanation) await explain({ target: { subject_id: explanation.subject_id, scope_type: explanation.target_scope_type, scope_id: explanation.target_scope_id, requested_access: explanation.decision.split(':')[1] as PolicyAccess } } as PolicyPreviewEntry)
      setNotice(t('policies.conflict.exceptionAccepted'))
    } catch (error) { setProblem(apiProblem(error, t)) }
    finally { setBusy(false) }
  }

  async function setPolicyLock(locked: boolean) {
    if (!selectedPolicy) return
    setDriftBusy(true); setDriftProblem(null); setDriftNotice(null)
    try {
      const updated = await apiRequest<Policy>(`/api/v1/guilds/${guild.guild_id}/policies/${selectedPolicy.policy_id}/${locked ? 'lock' : 'unlock'}`, {
        method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() },
        body: { expected_revision: selectedPolicy.revision },
      })
      await client.invalidateQueries({ queryKey: ['did', me.user.discord_user_id, guild.guild_id, 'policies'] })
      chooseCustom(updated)
      setDriftNotice(t(locked ? 'policies.drift.lockedNotice' : 'policies.drift.unlockedNotice'))
    } catch (error) { setDriftProblem(apiProblem(error, t)) }
    finally { setDriftBusy(false) }
  }

  async function repairDrift() {
    if (!selectedPolicy || selectedPolicy.locked) return
    setDriftBusy(true); setDriftProblem(null); setDriftNotice(null)
    try {
      const result = await apiRequest<{ preflight: { allowed: boolean; errors: string[] } }>(`/api/v1/guilds/${guild.guild_id}/policies/${selectedPolicy.policy_id}/drift-plan`, {
        method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() },
        body: { expected_revision: selectedPolicy.revision },
      })
      if (!result.preflight.allowed) {
        setDriftProblem(t('policies.drift.repairBlocked', { reason: result.preflight.errors.join(', ') || '—' }))
        return
      }
      navigate(`/guild/${guild.guild_id}/plans`)
    } catch (error) { setDriftProblem(apiProblem(error, t)) }
    finally { setDriftBusy(false) }
  }

  async function acceptDrift() {
    if (!selectedPolicy || selectedPolicy.locked) return
    setDriftBusy(true); setDriftProblem(null); setDriftNotice(null)
    try {
      const updated = await apiRequest<Policy>(`/api/v1/guilds/${guild.guild_id}/policies/${selectedPolicy.policy_id}/accept-drift`, {
        method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() },
        body: { expected_revision: selectedPolicy.revision },
      })
      await client.invalidateQueries({ queryKey: ['did', me.user.discord_user_id, guild.guild_id, 'policies'] })
      chooseCustom(updated)
      setDriftNotice(t('policies.drift.acceptedNotice'))
    } catch (error) { setDriftProblem(apiProblem(error, t)) }
    finally { setDriftBusy(false) }
  }

  async function toggleFavorite(favoriteKey: string) {
    if (favoriteBusy) return
    setFavoriteBusy(favoriteKey); setFavoriteProblem(null)
    try {
      const updated = await apiRequest<PolicyFavorites>(`/api/v1/guilds/${guild.guild_id}/policy-favorites`, {
        method: 'PATCH',
        body: { favorite_key: favoriteKey, pinned: !favoriteKeys.has(favoriteKey) },
      })
      client.setQueryData(['did', me.user.discord_user_id, guild.guild_id, 'policy-favorites'], updated)
    } catch (error) { setFavoriteProblem(apiProblem(error, t)) }
    finally { setFavoriteBusy(null) }
  }

  function favoriteToggle(favoriteKey: string, name: string) {
    const pinned = favoriteKeys.has(favoriteKey)
    return <button
      type="button"
      className={pinned ? 'policy-favorite-toggle pinned' : 'policy-favorite-toggle'}
      aria-pressed={pinned}
      aria-label={t(pinned ? 'policies.favorite.remove' : 'policies.favorite.add', { name })}
      title={t(pinned ? 'policies.favorite.remove' : 'policies.favorite.add', { name })}
      disabled={favoritesQuery.isLoading || Boolean(favoriteBusy)}
      onClick={() => void toggleFavorite(favoriteKey)}
    ><Star size={17} fill={pinned ? 'currentColor' : 'none'} /></button>
  }

  function nativeCard(native: NativePolicy) {
    const name = t(native.titleKey)
    const Icon = policyIcon(native)
    return <div className="policy-card-row" key={native.id}>
      <button type="button" className={selection?.kind === 'NATIVE' && selection.native.id === native.id ? 'policy-card selected' : 'policy-card'} onClick={() => chooseNative(native)}>
        <span className={`policy-intent-icon policy-intent-${native.family.toLocaleLowerCase()}`}><Icon size={19} /></span>
        <span className="policy-card-copy"><strong>{name}</strong><span>{t(native.summaryKey)}</span></span>
        <ChevronRight className="policy-card-arrow" size={17} aria-hidden="true" />
      </button>
      {favoriteToggle(`native:${native.id}`, name)}
    </div>
  }

  function customPolicyCard(policy: Policy) {
    const Icon = familyIcons[policyFamily(policy)]
    return <div className="policy-card-row" key={policy.policy_id}>
      <button type="button" className={selectedPolicy?.policy_id === policy.policy_id ? 'policy-card selected' : 'policy-card'} onClick={() => chooseCustom(policy)}>
        <span className={`policy-intent-icon policy-intent-${policyFamily(policy).toLocaleLowerCase()}`}><Icon size={19} /></span>
        <span className="policy-card-copy"><span className="policy-card-title"><strong>{policy.name}</strong><Badge tone={lifecycleTone[policy.lifecycle_state]}>{t(`policies.lifecycle.${policy.lifecycle_state}`)}</Badge></span><span>{policy.metadata.summary}</span></span>
        <ChevronRight className="policy-card-arrow" size={17} aria-hidden="true" />
      </button>
      {favoriteToggle(`custom:${policy.policy_id}`, policy.name)}
    </div>
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
  const drift = driftQuery.data
  const driftedEntries = drift?.entries.filter((entry) => entry.access_change !== 'UNCHANGED') ?? []
  const driftAccepted = drift?.warnings.includes('policy.drift.exception_accepted') ?? false
  const interventionRequired = selectedPolicy?.metadata.tags.includes('reconciler:intervention_required') ?? false
  const lastRepairVerified = selectedPolicy?.metadata.tags.includes('reconciler:repaired') ?? false
  const driftUnknown = Boolean(drift && (drift.impact.accuracy !== 'EXACT' || driftedEntries.some((entry) => entry.current.outcome === 'UNKNOWN' || entry.proposed.outcome === 'UNKNOWN' || entry.proposed.outcome === 'BLOCKED')))
  const temporaryAccess = temporaryQuery.data?.temporary_access ?? null
  const temporaryEditable = !temporaryAccess || ['SCHEDULED', 'INTERVENTION_REQUIRED', 'CANCELLED'].includes(temporaryAccess.status)
  const temporaryExpiryLabel = temporaryAccess ? new Intl.DateTimeFormat(i18n.language, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(temporaryAccess.expires_at)) : ''
  const resultAccesses = [...new Set(visibleDefinition?.effects.map((effect) => effect.access) ?? [])]
  const resultActors = activeNative?.audienceMode === 'EXCLUDE'
    ? t('policies.result.everyoneExcept', { roles: roleNames(editor.roleIds) || t('policies.result.noRoles'), interpolation: { escapeValue: false } })
    : roleNames(editor.roleIds) || t('policies.result.noRoles')
  const resultActions = resultAccesses.map((access) => t(`policies.access.${access}`)).join(', ').toLocaleLowerCase()

  return <section className="access-page policies-workbench bunny-access-page">
    <header className="access-hero bunny-access-header">
      <div className="bunny-access-heading"><span className="bunny-access-heading-icon"><ShieldCheck size={26} /></span><div><p className="access-eyebrow">{t('access.eyebrow')}</p><h1>{t('policies.title')}</h1><p>{t('policies.subtitle')}</p></div></div>
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

    <details className="access-panel zone-panel">
      <summary><small>{t('policies.zone.eyebrow')}</small><strong>{t('policies.zone.title')}</strong></summary>
      <p className="access-help">{t('policies.zone.help')}</p>
      {pairedZones.length > 0 && <ul className="zone-list">
        {pairedZones.map(({ group, publicResource, staffResource }) => (
          <li key={group.id} className="zone-card">
            <div className="zone-card-heading"><strong>{group.name}</strong><Badge>{t('policies.zone.didGrouping')}</Badge></div>
            <p className="zone-side"><span>{t('policies.zone.publicSide')}</span>{zoneResourceLabel(publicResource, targets) ?? t('policies.zone.unknownResource')}</p>
            <p className="zone-side">
              <span>{t('policies.zone.staffSide')}</span>{zoneResourceLabel(staffResource, targets) ?? t('policies.zone.unknownResource')}
              {staffResource.discord_channel_id && <button type="button" className="button quiet" onClick={() => configureStaffForZone(staffResource.discord_channel_id as string)}>{t('policies.zone.configureStaff')}</button>}
            </p>
          </li>
        ))}
      </ul>}
      {!zoneFormOpen
        ? <button type="button" className="button" onClick={() => setZoneFormOpen(true)}>{t('policies.zone.link')}</button>
        : <div className="zone-form">
          <label className="field"><span>{t('policies.zone.name')}</span><input value={zoneName} maxLength={128} onChange={(event) => setZoneName(event.target.value)} /></label>
          <label className="field"><span>{t('policies.zone.publicSide')}</span><select value={zonePublicValue} onChange={(event) => setZonePublicValue(event.target.value)}>
            <option value="">{t('policies.zone.pick')}</option>
            {zoneableTargets.map((target) => <option key={targetKey(target)} value={targetKey(target)}>{t(`policies.target.kind.${target.kind}`)} · {target.label}</option>)}
          </select></label>
          <label className="field"><span>{t('policies.zone.staffSide')}</span><select value={zoneStaffValue} onChange={(event) => setZoneStaffValue(event.target.value)}>
            <option value="">{t('policies.zone.pick')}</option>
            {zoneableTargets.map((target) => <option key={targetKey(target)} value={targetKey(target)}>{t(`policies.target.kind.${target.kind}`)} · {target.label}</option>)}
          </select></label>
          {zoneProblem && <p className="access-callout danger" role="alert">{zoneProblem}</p>}
          <div className="button-row">
            <button type="button" className="button primary" disabled={zoneBusy || !zoneName.trim() || !zonePublicValue || !zoneStaffValue || zonePublicValue === zoneStaffValue} onClick={() => void createPairedZoneFromForm()}>{t('policies.zone.create')}</button>
            <button type="button" className="button quiet" onClick={() => { setZoneFormOpen(false); setZoneProblem(null) }}>{t('common.cancel')}</button>
          </div>
        </div>}
    </details>

    <details className="access-panel preset-panel">
      <summary><small>{t('policies.preset.eyebrow')}</small><strong>{t('policies.preset.title')}</strong></summary>
      <p className="access-help">{t('policies.preset.help')}</p>
      {!presetOpen ? <>
        {availablePresets.length === 0 && <p className="access-help">{t('policies.preset.noneCompatible')}</p>}
        <div className="policy-card-list">
          {availablePresets.map((preset) => (
            <button type="button" className="policy-card" key={preset.id} onClick={() => { setPresetOpen(preset.id); setPresetName(t(preset.titleKey)); setPresetDescription(t(preset.summaryKey)) }}>
              <span className="policy-card-heading"><strong>{t(preset.titleKey)}</strong><Badge>{t('policies.preset.badge')}</Badge></span>
              <span>{t(preset.summaryKey)}</span>
              <small>{t(preset.helpKey)}</small>
            </button>
          ))}
        </div>
      </> : <div className="preset-form">
        <label className="field"><span>{t('policies.editor.name')}</span><input value={presetName} onChange={(event) => setPresetName(event.target.value)} /></label>
        <label className="field"><span>{t('policies.editor.description')}</span><input value={presetDescription} onChange={(event) => setPresetDescription(event.target.value)} /></label>

        {presetOpen === 'confidential' && <>
          {presetRolePicker('policies.preset.confidential.viewers', confidentialConfig.viewerRoleIds, (roleIds) => setConfidentialConfig((value) => ({ ...value, viewerRoleIds: roleIds })))}
          {presetRolePicker('policies.preset.confidential.managers', confidentialConfig.managerRoleIds, (roleIds) => setConfidentialConfig((value) => ({ ...value, managerRoleIds: roleIds })))}
          <label><input type="checkbox" checked={confidentialConfig.blockMentions} onChange={(event) => setConfidentialConfig((value) => ({ ...value, blockMentions: event.target.checked }))} /><span>{t('policies.preset.confidential.blockMentionsLabel')}</span></label>
          <label><input type="checkbox" checked={confidentialConfig.restrictThreads} onChange={(event) => setConfidentialConfig((value) => ({ ...value, restrictThreads: event.target.checked }))} /><span>{t('policies.preset.confidential.restrictThreadsLabel')}</span></label>
        </>}

        {presetOpen === 'announcement_channel' && <>
          {presetRolePicker('policies.preset.announcement.publishers', announcementConfig.publisherRoleIds, (roleIds) => setAnnouncementConfig((value) => ({ ...value, publisherRoleIds: roleIds })))}
          <label className="field"><span>{t('policies.options.reactions')}</span><select value={announcementConfig.reactionMode} onChange={(event) => setAnnouncementConfig((value) => ({ ...value, reactionMode: event.target.value as PolicyMode }))}>
            {(['INHERIT', 'EVERYONE', 'ONLY', 'NONE'] as const).map((mode) => <option key={mode} value={mode}>{t(`policies.mode.${mode}`)}</option>)}
          </select></label>
          <label className="field"><span>{t('policies.options.threads')}</span><select value={announcementConfig.threadMode} onChange={(event) => setAnnouncementConfig((value) => ({ ...value, threadMode: event.target.value as PolicyMode }))}>
            {(['INHERIT', 'EVERYONE', 'ONLY', 'NONE'] as const).map((mode) => <option key={mode} value={mode}>{t(`policies.mode.${mode}`)}</option>)}
          </select></label>
          <label className="field"><span>{t('policies.options.threadReplies')}</span><select value={announcementConfig.replyMode} onChange={(event) => setAnnouncementConfig((value) => ({ ...value, replyMode: event.target.value as PolicyMode }))}>
            {(['INHERIT', 'EVERYONE', 'ONLY', 'NONE'] as const).map((mode) => <option key={mode} value={mode}>{t(`policies.mode.${mode}`)}</option>)}
          </select><small>{t('policies.options.threadRepliesHelp')}</small></label>
          {announcementNeedsPublishers && <p className="access-callout warning">{t('policies.preset.announcement.audienceRequired')}</p>}
        </>}

        {presetOpen === 'support_zone' && <>
          {presetRolePicker('policies.preset.supportZone.supportGroup', supportZoneConfig.supportRoleIds, (roleIds) => setSupportZoneConfig((value) => ({ ...value, supportRoleIds: roleIds })))}
          <label className="field"><span>{t('policies.preset.supportZone.visibilityLabel')}</span><select value={supportZoneConfig.visibility} onChange={(event) => setSupportZoneConfig((value) => ({ ...value, visibility: event.target.value as 'OPEN' | 'PRIVATE' }))}>
            <option value="OPEN">{t('policies.preset.supportZone.visibilityOpenOption')}</option>
            <option value="PRIVATE">{t('policies.preset.supportZone.visibilityPrivateOption')}</option>
          </select></label>
          <label className="field"><span>{t('policies.preset.supportZone.writeLabel')}</span><select value={supportZoneConfig.writeMode} onChange={(event) => setSupportZoneConfig((value) => ({ ...value, writeMode: event.target.value as 'EVERYONE' | 'SUPPORT_ONLY' }))}>
            <option value="EVERYONE">{t('policies.preset.supportZone.writeEveryoneOption')}</option>
            <option value="SUPPORT_ONLY">{t('policies.preset.supportZone.writeSupportOnlyOption')}</option>
          </select></label>
        </>}

        <div className="preset-subrules">
          <strong>{t('policies.preset.subRulesTitle')}</strong>
          {presetSubRules.length === 0 && <p className="access-help">{t('policies.preset.noSubRules')}</p>}
          <ul>{presetSubRules.map((rule) => <li key={rule.key}>{t(rule.labelKey, { roles: roleNames(rule.roleIds) })}</li>)}</ul>
        </div>

        {presetProblem && <p className="access-callout danger" role="alert">{presetProblem}</p>}
        <div className="button-row">
          <button type="button" className="button primary" disabled={presetBusy || !presetName.trim() || presetSubRules.length === 0 || announcementNeedsPublishers} onClick={() => void createPresetDrafts()}>{t('policies.preset.create')}</button>
          <button type="button" className="button quiet" onClick={resetPresetForm}>{t('common.cancel')}</button>
        </div>
      </div>}
      {presetNotice && <p className="access-callout success" role="status">{presetNotice}</p>}
    </details>

    <div className="policy-layout">
      <article className="access-panel policy-catalog-panel">
        <div className="access-panel-heading"><div><small>{t('policies.step.policy')}</small><strong>{t('policies.catalog.title')}</strong></div><Badge>{t('policies.catalog.count', { count: availableNatives.length + customPolicies.length })}</Badge></div>
        <TextInput className="policy-intent-search" value={intentSearch} onChange={(event) => setIntentSearch(event.currentTarget.value)} placeholder={t('policies.intent.search')} aria-label={t('policies.intent.search')} leftSection={<Search size={16} />} />
        {favoritesQuery.isError && <p className="access-callout danger" role="alert">{t('policies.favorite.loadError')} <button type="button" className="button quiet" onClick={() => void favoritesQuery.refetch()}>{t('common.retry')}</button></p>}
        {favoriteProblem && <p className="access-callout danger" role="alert">{favoriteProblem}</p>}
        {visibleFavoriteNatives.length + visibleFavoriteCustomPolicies.length > 0 && <section className="policy-favorites" aria-labelledby="favorite-policy-title"><h2 id="favorite-policy-title">{t('policies.favorite.title')}</h2><div className="policy-card-list">
          {visibleFavoriteNatives.map(nativeCard)}
          {visibleFavoriteCustomPolicies.map(customPolicyCard)}
        </div></section>}
        <section aria-labelledby="native-policy-title"><h2 id="native-policy-title">{t('policies.native.title')}</h2><div className="policy-card-list">
          {visibleOtherNatives.map(nativeCard)}
        </div></section>
        <section aria-labelledby="custom-policy-title"><h2 id="custom-policy-title">{t('policies.custom.title')}</h2><div className="policy-card-list">
          {customPolicies.length === 0 && <p className="access-help">{t('policies.custom.empty')}</p>}
          {visibleOtherCustomPolicies.map(customPolicyCard)}
        </div></section>
      </article>

      <article className="access-panel policy-editor-panel">
        {!selection ? <div className="access-empty"><span>◇</span><p>{t('policies.editor.empty')}</p></div> : <>
          <div className="access-panel-heading"><div><small>{selection.kind === 'NATIVE' ? t('policies.origin.did') : t('policies.origin.custom')}</small><strong>{editor.name || t('policies.editor.untitled')}</strong></div>{selectedPolicy && <span className="policy-card-badges"><Badge tone={lifecycleTone[selectedPolicy.lifecycle_state]}>{t(`policies.lifecycle.${selectedPolicy.lifecycle_state}`)}</Badge>{selectedPolicy.locked && <Badge tone="warning">{t('policies.drift.lockedBadge')}</Badge>}</span>}</div>
          {selectedPolicy && selectedPolicy.lifecycle_state !== 'DRAFT' && <p className="access-callout warning">{t('policies.editor.immutable')}</p>}
          {selectedPolicy?.lifecycle_state === 'ACTIVE' && <section className={`policy-temporary-access ${temporaryAccess?.status === 'INTERVENTION_REQUIRED' ? 'danger' : ''}`} aria-labelledby="policy-temporary-title">
            <div className="policy-compliance-heading"><div><small>{t('policies.temporary.eyebrow')}</small><h2 id="policy-temporary-title">{t('policies.temporary.title')}</h2></div>{temporaryAccess && temporaryAccess.status !== 'CANCELLED' && <Badge tone={temporaryAccess.status === 'INTERVENTION_REQUIRED' ? 'danger' : temporaryAccess.status === 'REMOVED' ? 'ok' : 'warning'}>{t(`policies.temporary.status.${temporaryAccess.status}`)}</Badge>}</div>
            {temporaryQuery.isLoading ? <p>{t('policies.temporary.loading')}</p> : temporaryQuery.isError ? <p className="access-callout danger" role="alert">{t('policies.temporary.loadFailed')}</p> : <>
              {temporaryAccess && temporaryAccess.status !== 'CANCELLED' && <p>{t('policies.temporary.expires', { date: temporaryExpiryLabel })}</p>}
              {temporaryAccess?.status === 'INTERVENTION_REQUIRED' && <p className="access-callout danger" role="alert">{t('policies.temporary.intervention', { reason: temporaryAccess.last_error ?? t('policies.temporary.unknownReason') })}</p>}
              {temporaryAccess?.status === 'REMOVAL_SCHEDULED' || temporaryAccess?.status === 'PROCESSING' ? <p>{t('policies.temporary.removing')}</p> : null}
              {temporaryEditable && <div className="policy-temporary-controls">
                <p>{t('policies.temporary.help')}</p>
                <div className="button-row" aria-label={t('policies.temporary.shortcuts')}>
                  <button type="button" className="button quiet" disabled={temporaryBusy || !canPrepare} onClick={() => void scheduleTemporaryAccess(1)}>{t('policies.temporary.oneHour')}</button>
                  <button type="button" className="button quiet" disabled={temporaryBusy || !canPrepare} onClick={() => void scheduleTemporaryAccess(24)}>{t('policies.temporary.oneDay')}</button>
                  <button type="button" className="button quiet" disabled={temporaryBusy || !canPrepare} onClick={() => void scheduleTemporaryAccess(24 * 7)}>{t('policies.temporary.sevenDays')}</button>
                </div>
                <label className="field"><span>{t('policies.temporary.custom')}</span><input type="datetime-local" min={localDateTimeInput(new Date(Date.now() + 5 * 60 * 1000))} value={temporaryUntil} onChange={(event) => setTemporaryUntil(event.target.value)} /></label>
                <div className="button-row"><button type="button" className="button primary" disabled={temporaryBusy || !canPrepare || !temporaryUntil} onClick={() => void scheduleTemporaryAccess()}>{t(temporaryAccess?.status === 'SCHEDULED' ? 'policies.temporary.reschedule' : 'policies.temporary.schedule')}</button>{temporaryAccess && ['SCHEDULED', 'INTERVENTION_REQUIRED'].includes(temporaryAccess.status) && <button type="button" className="button quiet" disabled={temporaryBusy || !canActivate} onClick={() => void cancelTemporaryAccess()}>{t('policies.temporary.cancel')}</button>}</div>
              </div>}
              {temporaryAccess?.removal_plan_id && <button type="button" className="button quiet" onClick={() => navigate(`/guild/${guild.guild_id}/plans`)}>{t('policies.temporary.openPlan')}</button>}
            </>}
            {temporaryProblem && <p className="access-callout danger" role="alert">{temporaryProblem}</p>}
          </section>}
          {selectedPolicy?.lifecycle_state === 'ACTIVE' && <section className={`policy-compliance ${interventionRequired || driftUnknown ? 'danger' : driftedEntries.length ? 'warning' : 'ok'}`} aria-labelledby="policy-compliance-title">
            <div className="policy-compliance-heading"><div><small>{t('policies.drift.eyebrow')}</small><h2 id="policy-compliance-title">{t(interventionRequired || driftUnknown ? 'policies.drift.interventionTitle' : driftedEntries.length ? selectedPolicy.locked ? 'policies.drift.autoRepairTitle' : driftAccepted ? 'policies.drift.acceptedTitle' : 'policies.drift.detectedTitle' : 'policies.drift.compliantTitle')}</h2></div><Badge tone={interventionRequired || driftUnknown ? 'danger' : driftedEntries.length ? 'warning' : 'ok'}>{t(interventionRequired || driftUnknown ? 'policies.drift.interventionBadge' : driftedEntries.length ? 'policies.drift.driftBadge' : 'policies.drift.compliantBadge')}</Badge></div>
            {driftQuery.isLoading ? <p>{t('policies.drift.checking')}</p> : driftQuery.isError ? <p className="access-callout danger" role="alert">{t('policies.drift.checkFailed')}</p> : <>
              <p>{t(interventionRequired || driftUnknown ? 'policies.drift.interventionHelp' : driftedEntries.length ? selectedPolicy.locked ? 'policies.drift.autoRepairHelp' : driftAccepted ? 'policies.drift.acceptedHelp' : 'policies.drift.detectedHelp' : lastRepairVerified ? 'policies.drift.repairedHelp' : 'policies.drift.compliantHelp')}</p>
              {driftedEntries.length > 0 && <ul className="policy-drift-causes">{driftedEntries.slice(0, 6).map((entry, index) => <li key={`${entry.target.subject_id}-${entry.target.scope_id}-${entry.target.requested_access}-${index}`}>{t('policies.drift.cause', { member: partialMember(entry.target.subject_id), access: t(`policies.access.${entry.target.requested_access}`), current: t(`policies.outcome.${entry.current.outcome}`), expected: t(`policies.outcome.${entry.proposed.outcome}`) })}</li>)}</ul>}
              {driftedEntries.length > 6 && <p className="access-help">{t('policies.drift.moreCauses', { count: driftedEntries.length - 6 })}</p>}
              {driftedEntries.length > 0 && <details><summary>{t('policies.expert.discordDetails')}</summary>{driftedEntries.map((entry, index) => <div key={`discord-drift-${index}`}><p>{entry.proposed.discord_permissions.join(', ') || '—'}</p><code>allow={entry.proposed.discord_allow_bits} · deny={entry.proposed.discord_deny_bits}</code></div>)}</details>}
            </>}
            {driftProblem && <p className="access-callout danger" role="alert">{driftProblem}</p>}
            {driftNotice && <p className="access-callout success" role="status">{driftNotice}</p>}
            <div className="button-row">
              <button type="button" className={selectedPolicy.locked ? 'button quiet' : 'button primary'} disabled={driftBusy || canUpdate !== 'CAN'} onClick={() => void setPolicyLock(!selectedPolicy.locked)}>{t(selectedPolicy.locked ? 'policies.drift.unlock' : 'policies.drift.lock')}</button>
              {!selectedPolicy.locked && driftedEntries.length > 0 && !driftAccepted && !driftUnknown && <><button type="button" className="button primary" disabled={driftBusy || !canPrepare} onClick={() => void repairDrift()}>{t('policies.drift.repair')}</button><button type="button" className="button quiet" disabled={driftBusy || canUpdate !== 'CAN'} onClick={() => void acceptDrift()}>{t('policies.drift.accept')}</button></>}
              {driftQuery.isError && <button type="button" className="button quiet" onClick={() => void driftQuery.refetch()}>{t('common.retry')}</button>}
            </div>
          </section>}
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
            {activeNative?.editorKind !== 'BOT' && activeNative?.editorKind !== 'NAMED_AUDIENCE' && activeNative?.editorKind !== 'ROLE_BUT_NOT' && (activeNative?.editorKind === undefined || activeNative.editorKind === 'AUDIENCE' || editor.reactionMode === 'ONLY') && rolePicker('policies.audience.roles', editor.roleIds, (roleIds) => setEditor((value) => ({ ...value, roleIds })), editorDisabled)}
            {activeNative?.editorKind === 'NAMED_AUDIENCE' && <div className="policy-named-audience">
              {namedAudience ? <p>{t(activeNative.requiresNamedAudience === 'STAFF' ? 'policies.audience.staffDefinition' : 'policies.audience.confirmedDefinition', { roles: namedAudience.roleIds.map((id) => roles.find((role) => role.id === id)?.name ?? id).join(' + ') || '—' })}</p>
                : <p className="access-callout warning">{t(activeNative.requiresNamedAudience === 'STAFF' ? 'policies.audience.staffConfigRequired' : 'policies.audience.confirmedConfigRequired')}</p>}
              <button type="button" className="button quiet" onClick={() => { setAudienceDraftRoleIds(namedAudience ? [...namedAudience.roleIds] : [...staffSuggestion]); setAudienceEditorOpen((value) => !value) }}>{t('policies.audience.configure')}</button>
              {staffSuggestion.length > 0 && !namedAudience && !audienceEditorOpen && <p className="access-help">{t('policies.audience.suggestion', { roles: staffSuggestion.map((id) => roles.find((role) => role.id === id)?.name ?? id).join(' + ') })}</p>}
              {audienceEditorOpen && <div className="policy-named-audience-editor">
                <p className="access-help">{t('policies.audience.suggestionHelp')}</p>
                {rolePicker('policies.audience.roles', audienceDraftRoleIds, setAudienceDraftRoleIds)}
                <button type="button" className="button primary" disabled={audienceBusy || audienceDraftRoleIds.length === 0} onClick={() => void (async () => {
                  setAudienceBusy(true)
                  try {
                    await saveNamedAudience(activeNative.requiresNamedAudience as 'STAFF' | 'CONFIRMED_MEMBER', existingAudienceScope ?? null, t(activeNative.requiresNamedAudience === 'STAFF' ? 'policies.audience.staffTitle' : 'policies.audience.confirmedTitle'), audienceDraftRoleIds)
                    setEditor((value) => ({ ...value, roleIds: [...audienceDraftRoleIds] }))
                    setAudienceEditorOpen(false)
                  } catch (error) { setProblem(apiProblem(error, t)) } finally { setAudienceBusy(false) }
                })()}>{t('policies.audience.save')}</button>
              </div>}
            </div>}
            {activeNative?.editorKind === 'ROLE_BUT_NOT' && <div className="policy-role-but-not">
              <p><strong>{t('policies.audience.has')}</strong></p>
              {rolePicker('policies.audience.has', editor.roleIds, (roleIds) => setEditor((value) => ({ ...value, roleIds })), editorDisabled)}
              <p><strong>{t('policies.audience.butNot')}</strong></p>
              {rolePicker('policies.audience.butNot', editor.excludedRoleIds, (excludedRoleIds) => setEditor((value) => ({ ...value, excludedRoleIds })), editorDisabled)}
            </div>}
            {activeNative?.id === 'private_voice' && <div className="policy-staff-option"><label><input type="checkbox" checked={editor.includeStaff} disabled={editorDisabled} onChange={(event) => setEditor((value) => ({ ...value, includeStaff: event.target.checked }))} /><span>{t('policies.voice.staffAlwaysJoin')}</span></label>{editor.includeStaff && <><p className="access-callout warning">{t('policies.voice.staffExplicit')}</p>{rolePicker('policies.audience.staffTitle', editor.staffRoleIds, (staffRoleIds) => setEditor((value) => ({ ...value, staffRoleIds })), editorDisabled)}</>}</div>}
            {activeNative?.id === 'open_read_limited_write' && <div className="policy-secondary-options"><label className="field"><span>{t('policies.options.reactions')}</span><select value={editor.reactionMode} disabled={editorDisabled} onChange={(event) => setEditor((value) => ({ ...value, reactionMode: event.target.value as PolicyMode }))}>{(['INHERIT', 'EVERYONE', 'ONLY', 'NONE'] as const).map((mode) => <option key={mode} value={mode}>{t(`policies.mode.${mode}`)}</option>)}</select></label><label className="field"><span>{t('policies.options.threads')}</span><select value={editor.threadMode} disabled={editorDisabled} onChange={(event) => setEditor((value) => ({ ...value, threadMode: event.target.value as PolicyMode }))}>{(['INHERIT', 'EVERYONE', 'ONLY', 'NONE'] as const).map((mode) => <option key={mode} value={mode}>{t(`policies.mode.${mode}`)}</option>)}</select></label><label className="field"><span>{t('policies.options.threadReplies')}</span><select value={editor.replyMode} disabled={editorDisabled} onChange={(event) => setEditor((value) => ({ ...value, replyMode: event.target.value as PolicyMode }))}>{(['INHERIT', 'EVERYONE', 'ONLY', 'NONE'] as const).map((mode) => <option key={mode} value={mode}>{t(`policies.mode.${mode}`)}</option>)}</select><small>{t('policies.options.threadRepliesHelp')}</small></label></div>}
            {(activeNative?.id === 'at_least_one_role' || activeNative?.id === 'all_roles_required' || activeNative?.id === 'role_but_not_role') && <p className="access-help">{t(`policies.audience.example.${activeNative.id}`, { roles: (activeNative.id === 'role_but_not_role' ? [...editor.roleIds, ...editor.excludedRoleIds] : editor.roleIds).map((id) => roles.find((role) => role.id === id)?.name ?? id).slice(0, 2).join(' / ') || '—' })}</p>}
            <div className="policy-human-result"><span className="policy-result-icon"><ShieldCheck size={19} /></span><div><strong>{t('policies.result.title')}</strong><p>{t('policies.result.sentence', { actors: resultActors, actions: resultActions || t('policies.result.noAction'), target: selectedTarget?.label ?? t('policies.result.thisServer'), interpolation: { escapeValue: false } })}</p></div>{resultAccesses.map((access) => <span key={access}>{t(`policies.access.${access}`)}</span>)}</div>
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
            {selectedPolicy && selectedPolicy.lifecycle_state !== 'RETIRED' && <button type="button" className="button danger" disabled={busy || canRetire !== 'CAN'} onClick={() => void openDeletion()}>{t('policies.delete.action')}</button>}
            {canReapplyCategoryPolicy && <button type="button" className="button quiet" onClick={() => { setReapplyOpen(true); void loadReapplyPreview() }}>{t('policies.reapply.action')}</button>}
          </div>
          {selectedPolicy?.lifecycle_state === 'DRAFT' && <div className="draft-safety"><Badge tone="warning">{t('policies.lifecycle.DRAFT')}</Badge><span>{t('policies.draft.safety')}</span></div>}
          {reapplyNotice && <p className="access-callout success" role="status">{reapplyNotice}</p>}
        </>}
        {problem && <p className="access-callout danger" role="alert">{problem}</p>}{notice && <p className="access-callout success" role="status">{notice}</p>}
      </article>
    </div>

    {historyOpen && selectedPolicy && <article className="access-panel policy-history-panel"><div className="access-panel-heading"><div><small>{selectedPolicy.name}</small><strong>{t('policies.history.title')}</strong></div></div>
      {versionsQuery.isLoading ? <Skeleton /> : versionsQuery.isError ? <ErrorState retry={() => void versionsQuery.refetch()} /> : <ol>{(versionsQuery.data?.versions ?? []).map((version) => <li key={version.version_id}><div><strong>{t('policies.revision', { revision: version.revision })}</strong><span>{new Intl.DateTimeFormat(i18n.language, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(version.created_at))}</span><small>{t(`policies.change.${version.change_kind}`, { kind: version.change_kind })} · {t('policies.history.author', { author: partialMember(version.author_user_id) })}</small></div><button type="button" className="button quiet" disabled={busy || canCreate !== 'CAN'} onClick={() => void draftFromVersion(version)}>{t('policies.history.createDraft')}</button></li>)}</ol>}
      <p className="access-help">{t('policies.history.safety')}</p>
    </article>}

    {reapplyOpen && selectedPolicy && <article className="access-panel policy-preview-panel">
      <div className="access-panel-heading"><div><small>{t('policies.reapply.eyebrow')}</small><strong>{t('policies.reapply.title')}</strong></div>{reapplyPreview && <Badge tone={reapplyPreview.impact.accuracy === 'EXACT' ? 'ok' : 'warning'}>{t(`policies.accuracy.${reapplyPreview.impact.accuracy}`)}</Badge>}</div>
      <p className="access-help">{t('policies.reapply.help')}</p>
      {reapplyBusy && !reapplyPreview ? <Skeleton /> : reapplyPreview && <>
        <div className="policy-impact-grid"><div><strong>{reapplyPreview.impact.access_gains}</strong><span>{t('policies.impact.gains')}</span></div><div><strong>{reapplyPreview.impact.access_losses}</strong><span>{t('policies.impact.losses')}</span></div><div><strong>{reapplyPreview.impact.affected_members}</strong><span>{t('policies.impact.members')}</span></div><div><strong>{reapplyPreview.impact.affected_roles}</strong><span>{t('policies.impact.roles')}</span></div><div><strong>{reapplyPreview.impact.affected_resources}</strong><span>{t('policies.impact.resources')}</span></div><div><strong>{reapplyPreview.impact.conflicts}</strong><span>{t('policies.impact.conflicts')}</span></div></div>
        {reapplyPreview.impact.diagnostics.map((diagnostic) => <p className="access-callout warning" key={diagnostic}>{t(`policies.diagnostic.${diagnostic}`, { diagnostic })}</p>)}
      </>}
      {reapplyProblem && <p className="access-callout danger" role="alert">{reapplyProblem}</p>}
      <div className="button-row">
        {!reapplyPlan
          ? <button type="button" className="button primary" disabled={reapplyBusy || !reapplyPreview || reapplyPreview.impact.accuracy !== 'EXACT'} onClick={() => void prepareReapplyPlan()}>{t('policies.reapply.preparePlan')}</button>
          : <button type="button" className="button primary" disabled={reapplyBusy} onClick={() => void confirmReapply()}>{t('policies.reapply.confirm')}</button>}
        <button type="button" className="button quiet" onClick={resetReapply}>{t('common.cancel')}</button>
      </div>
    </article>}

    {selectedPolicy?.lifecycle_state === 'DRAFT' && <article className="access-panel policy-preview-panel"><div className="access-panel-heading"><div><small>{t('policies.step.preview')}</small><strong>{t('policies.preview.title')}</strong></div>{preview && <Badge tone={preview.impact.accuracy === 'EXACT' ? 'ok' : 'warning'}>{t(`policies.accuracy.${preview.impact.accuracy}`)}</Badge>}</div>
      {!preview ? <div className="policy-preview-empty"><p>{t('policies.preview.help')}</p><button type="button" className="button primary" disabled={busy} onClick={() => void loadPreview()}>{t('policies.preview.action')}</button></div> : <>
        <div className="policy-impact-grid"><div><strong>{preview.impact.access_gains}</strong><span>{t('policies.impact.gains')}</span></div><div><strong>{preview.impact.access_losses}</strong><span>{t('policies.impact.losses')}</span></div><div><strong>{preview.impact.affected_members}</strong><span>{t('policies.impact.members')}</span></div><div><strong>{preview.impact.affected_roles}</strong><span>{t('policies.impact.roles')}</span></div><div><strong>{preview.impact.affected_resources}</strong><span>{t('policies.impact.resources')}</span></div><div><strong>{preview.impact.conflicts}</strong><span>{t('policies.impact.conflicts')}</span></div></div>
        {preview.impact.diagnostics.map((diagnostic) => <p className="access-callout warning" key={diagnostic}>{t(`policies.diagnostic.${diagnostic}`, { diagnostic })}</p>)}
        <div className="policy-preview-entries">{preview.entries.map((entry, index) => <article key={`${entry.target.subject_id}-${entry.target.scope_id}-${entry.target.requested_access}-${index}`} className={entry.proposed.outcome === 'BLOCKED' || entry.proposed.outcome === 'UNKNOWN' ? 'problem' : ''}>
          <div className="policy-entry-heading"><div><strong>{t('policies.member.partial', { suffix: partialMember(entry.target.subject_id) })}</strong><small>{t(`policies.access.${entry.target.requested_access}`)}</small></div><Badge tone={entry.proposed.outcome === 'CAN' ? 'ok' : entry.proposed.outcome === 'CANNOT' ? 'danger' : 'warning'}>{t(`policies.outcome.${entry.proposed.outcome}`)}</Badge></div>
          <p>{t('policies.preview.change', { before: t(`policies.outcome.${entry.current.outcome}`), after: t(`policies.outcome.${entry.proposed.outcome}`) })}</p>
          {[...new Set([...entry.proposed.incomplete_reasons, ...entry.diagnostics])].map((reason) => <p className="access-callout warning" key={reason}>{t('policies.reason', { reason })}</p>)}
          {entry.proposed.conflicts.map((conflict, conflictIndex) => <div className="policy-conflict" key={`${conflict.policy_ids.join('-')}-${conflictIndex}`}><strong>{t('policies.conflict.member', { member: partialMember(entry.target.subject_id) })}</strong><p>{t('policies.conflict.sources', { sources: conflict.policy_ids.map(policyName).join(' / '), effects: conflict.effects.join(' / ') })}</p><p>{conflict.outcome === 'RESOLVED' ? t('policies.conflict.winner', { winner: conflict.winning_policy_ids.map(policyName).join(', '), rule: conflict.resolution_rule ?? '—' }) : t('policies.conflict.blocked')}</p><button type="button" className="button quiet" onClick={() => setRemediationKey(remediationKey === `${index}:${conflictIndex}` ? null : `${index}:${conflictIndex}`)}>{t('policies.conflict.resolve')}</button>{remediationKey === `${index}:${conflictIndex}` && <p className="access-help">{t('policies.conflict.option.explainFirst')}</p>}</div>)}
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
      {(explanation.blacklist_regrants ?? []).map((regrant, index) => <div className="policy-conflict" key={`regrant-${index}`}>
        <strong>{t('policies.conflict.blacklistBypassed', { member: partialMember(explanation.subject_id), roles: regrant.regranting_role_ids.map((cause) => roles.find((role) => role.id === cause.role_id)?.name ?? cause.role_id).join(', ') || '—' })}</strong>
        <p>{t('policies.conflict.blacklistExcludedBy', { policy: policyName(regrant.excluding_policy_id), roles: regrant.excluding_role_ids.map((id) => roles.find((role) => role.id === id)?.name ?? id).join(', ') })}</p>
        <p>{t('policies.conflict.blacklistRegrantedBy', { policy: policyName(regrant.regranting_policy_id) })}</p>
        {regrant.accepted ? <Badge tone="ok">{t('policies.conflict.exceptionVoulue')}</Badge> : <button type="button" className="button quiet" disabled={busy} onClick={() => void acceptException(regrant.excluding_policy_id, regrant.regranting_policy_id)}>{t('policies.conflict.acceptException')}</button>}
      </div>)}
      {(explanation.conflict_explanations ?? []).filter((item) => item.causing_roles.length > 0).map((item, index) => <div className="policy-conflict" key={`explain-${index}`}>
        <strong>{t('policies.conflict.roleCause', { roles: item.causing_roles.map((cause) => roles.find((role) => role.id === cause.role_id)?.name ?? cause.role_id).join(', ') })}</strong>
        {item.accepted ? <Badge tone="ok">{t('policies.conflict.exceptionVoulue')}</Badge> : <button type="button" className="button quiet" disabled={busy} onClick={() => void acceptException(item.conflict.policy_ids[0] ?? '', item.conflict.policy_ids[1] ?? '')}>{t('policies.conflict.acceptException')}</button>}
        <div className="observable-remediation-list">{(item.remediations ?? []).map((remediation) => <article key={`${remediation.kind}-${remediation.target_id}`}>
          <strong>{t(`policies.conflict.remediation.${remediation.kind}`)}</strong>
          <p>{t('policies.conflict.remediation.collateralPermissions', { permissions: remediation.collateral_losses.join(', ') || t('policies.explain.none') })}</p>
          <p>{t('policies.conflict.remediation.collateralScope', { scope: remediation.collateral_scope.map(policyName).join(', ') || t('policies.explain.none') })}</p>
          <small>{t('policies.conflict.remediation.separatePlan')}</small>
          <button type="button" className="button quiet" onClick={() => navigate(`/guild/${guild.guild_id}/${remediation.route}`)}>{t('policies.conflict.remediation.review')}</button>
        </article>)}</div>
      </div>)}
      {explanation.observable_access_conflict && <section className="policy-conflict observable-conflict" aria-label={t('policies.conflict.observable.title')}>
        <div className="access-panel-heading"><div><small>{t('policies.conflict.observable.eyebrow')}</small><strong>{t('policies.conflict.observable.title')}</strong></div><Badge tone="danger">{t('policies.conflict.observable.badge')}</Badge></div>
        <p>{t('policies.conflict.observable.summary', { member: partialMember(explanation.observable_access_conflict.member_id), resource: explanation.observable_access_conflict.resource_id, policies: explanation.observable_access_conflict.policy_ids.map(policyName).join(', ') || '—' })}</p>
        <p>{t('policies.conflict.observable.expectedActual', { expected: t(`policies.outcome.${explanation.observable_access_conflict.expected_outcome}`), actual: t(`policies.conflict.actual.${explanation.observable_access_conflict.actual_outcome}`) })}</p>
        <div className="observable-cause-list">
          {[...explanation.observable_access_conflict.granting_causes, ...explanation.observable_access_conflict.denying_causes].map((cause, index) => <article key={`${cause.kind}-${cause.source_id ?? 'none'}-${index}`}>
            <strong>{t(`policies.conflict.cause.${cause.kind}`)}</strong>
            <p>{t('policies.conflict.observable.cause', { source: cause.source_name ?? cause.source_id ?? '—', permissions: cause.permission_names.join(', ') || '—' })}</p>
            {cause.inherited_from_category_id && <small>{t('policies.conflict.observable.inherited', { category: cause.inherited_from_category_id })}</small>}
          </article>)}
        </div>
        <strong className="observable-remediation-heading">{t('policies.conflict.remediation.title')}</strong>
        {explanation.observable_access_conflict.remediations.length === 0
          ? <p className="access-callout warning">{t('policies.conflict.remediation.none')}</p>
          : <div className="observable-remediation-list">{explanation.observable_access_conflict.remediations.map((remediation) => <article key={`${remediation.kind}-${remediation.target_id}`}>
              <strong>{t(`policies.conflict.remediation.${remediation.kind}`)}</strong>
              <p>{t('policies.conflict.remediation.collateralPermissions', { permissions: remediation.collateral_losses.join(', ') || t('policies.explain.none') })}</p>
              <p>{t('policies.conflict.remediation.collateralScope', { scope: remediation.collateral_scope.join(', ') || t('policies.explain.none') })}</p>
              <small>{t('policies.conflict.remediation.separatePlan')}</small>
              <button type="button" className="button quiet" onClick={() => navigate(`/guild/${guild.guild_id}/${remediation.route}`)}>{t('policies.conflict.remediation.review')}</button>
            </article>)}</div>}
      </section>}
      <details><summary>{t('policies.expert.discordDetails')}</summary><p>{explanation.discord_permissions.join(', ') || '—'}</p><code>allow={explanation.discord_allow_bits} · deny={explanation.discord_deny_bits}</code></details>
      {expert && <pre>{JSON.stringify(explanation, null, 2)}</pre>}
    </article>}
    <dialog ref={deleteDialogRef} className="access-panel policy-delete-dialog" aria-labelledby="policy-delete-title" onCancel={(event) => { event.preventDefault(); closeDeletion() }}>
      <div className="access-panel-heading"><div><small>{t('policies.delete.eyebrow')}</small><strong id="policy-delete-title">{t('policies.delete.title', { name: selectedPolicy?.name ?? '' })}</strong></div><button type="button" className="button quiet" onClick={closeDeletion}>{t('common.cancel')}</button></div>
      <p>{t('policies.delete.help')}</p>
      {deleteBusy && !deletionPreview ? <Skeleton /> : deletionPreview && <>
        <div className="policy-delete-dependencies">
          <div><strong>{deletionPreview.plans.length}</strong><span>{t('policies.delete.plans')}</span></div>
          <div><strong>{deletionPreview.referencing_policies.length}</strong><span>{t('policies.delete.references')}</span></div>
          <div><strong>{deletionPreview.bulk_operation_ids.length}</strong><span>{t('policies.delete.bulk')}</span></div>
          <div><strong>{deletionPreview.scope_binding_count}</strong><span>{t('policies.delete.bindings')}</span></div>
        </div>
        {deletionPreview.plans.length > 0 && <p className="access-callout warning">{t('policies.delete.historyPreserved')}</p>}
        {deletionPreview.referencing_policies.map((value) => <p className="access-help" key={value.policy_id}>{t('policies.delete.referenceDetail', { name: value.name, kinds: value.reference_kinds.join(', ') })}</p>)}
        {deletionPreview.access_impact && <div className="policy-impact-grid"><div><strong>{deletionPreview.access_impact.impact.access_gains}</strong><span>{t('policies.impact.gains')}</span></div><div><strong>{deletionPreview.access_impact.impact.access_losses}</strong><span>{t('policies.impact.losses')}</span></div><div><strong>{deletionPreview.access_impact.impact.affected_members}</strong><span>{t('policies.impact.members')}</span></div><div><strong>{deletionPreview.access_impact.impact.affected_resources}</strong><span>{t('policies.impact.resources')}</span></div></div>}
        <fieldset className="policy-delete-strategies"><legend>{t('policies.delete.strategy')}</legend>{deletionPreview.strategies.map((value) => <label key={value.strategy} className={!value.available ? 'disabled' : ''}><input type="radio" name="policy-delete-strategy" value={value.strategy} checked={deletionStrategy === value.strategy} disabled={!value.available} onChange={() => setDeletionStrategy(value.strategy)} /><span><strong>{t(`policies.delete.${value.strategy}.title`)}</strong><small>{t(`policies.delete.${value.strategy}.help`)}</small></span></label>)}</fieldset>
        {deletionStrategy === 'REPLACE' && <label className="field"><span>{t('policies.delete.replacement')}</span><select value={replacementPolicyId} onChange={(event) => setReplacementPolicyId(event.target.value)}><option value="">{t('policies.delete.replacementNone')}</option>{deletionPreview.available_replacements.map((value) => <option value={value.policy_id} key={value.policy_id}>{value.name}</option>)}</select></label>}
        {deletionPreview.strategies.find((value) => value.strategy === deletionStrategy)?.requires_plan && <p className="access-callout warning">{t('policies.delete.separatePlan')}</p>}
      </>}
      {deleteProblem && <p className="access-callout danger" role="alert">{deleteProblem}</p>}
      <div className="button-row"><button type="button" className="button danger" disabled={deleteBusy || !deletionPreview || deletionStrategy === 'REPLACE' && !replacementPolicyId} onClick={() => void confirmDeletion()}>{t('policies.delete.confirm')}</button><button type="button" className="button quiet" onClick={closeDeletion}>{t('common.cancel')}</button></div>
    </dialog>
  </section>
}

export { nativePolicies }
