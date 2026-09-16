import type { Policy, PolicyAccess, PolicyCondition, PolicyEffect, PolicyScopeType } from '../../api/types'
import type { NamedAudienceKind } from './audiences'

export type PolicyTargetKind = 'GUILD' | 'LOGICAL_GROUP' | 'CATEGORY' | 'TEXT_CHANNEL' | 'VOICE_CHANNEL' | 'ROLE'
export type NativePolicyId =
  | 'visible_only'
  | 'visible_except'
  | 'write_only'
  | 'write_except'
  | 'open_read_limited_write'
  | 'private_space'
  | 'staff_only'
  | 'confirmed_members_only'
  | 'at_least_one_role'
  | 'all_roles_required'
  | 'role_but_not_role'
  | 'voice_join_no_speak'
  | 'voice_speakers'
  | 'private_voice'
  | 'voice_managers'
  | 'thread_creators'
  | 'reactions'
  | 'mentions'
  | 'bot_minimal'

export type PolicyMode = 'INHERIT' | 'EVERYONE' | 'ONLY' | 'NONE'
export type BotFunction = 'READ' | 'WRITE' | 'MANAGE' | 'THREADS' | 'VOCAL'

export type NativePolicy = {
  id: NativePolicyId
  family: 'VISIBILITY' | 'WRITING' | 'AUDIENCE' | 'ZONE' | 'VOCAL' | 'THREADS' | 'REACTIONS' | 'MENTIONS' | 'BOTS'
  titleKey: string
  summaryKey: string
  helpKey: string
  audienceKey: string
  compatibility: readonly PolicyTargetKind[]
  access: readonly PolicyAccess[]
  audienceMode: 'INCLUDE' | 'EXCLUDE'
  editorKind?: 'AUDIENCE' | 'MODE' | 'MENTIONS' | 'BOT' | 'NAMED_AUDIENCE' | 'ROLE_BUT_NOT'
  wizardCompatible?: boolean
  matrixCompatible?: boolean
  /** REQ-AP-ZONE-010/012, REQ-AP-ZONE-020/022: roles come from the guild's
   * persisted Named Audience definition, never an ad-hoc per-Policy pick. */
  requiresNamedAudience?: NamedAudienceKind
}

const RESOURCE_TARGETS = ['GUILD', 'LOGICAL_GROUP', 'CATEGORY', 'TEXT_CHANNEL'] as const

export const nativePolicies: readonly NativePolicy[] = [
  { id: 'visible_only', family: 'VISIBILITY', titleKey: 'policies.native.visibleOnly.title', summaryKey: 'policies.native.visibleOnly.summary', helpKey: 'policies.native.visibleOnly.help', audienceKey: 'policies.audience.whoCanSee', compatibility: RESOURCE_TARGETS, access: ['VIEW'], audienceMode: 'INCLUDE' },
  { id: 'visible_except', family: 'VISIBILITY', titleKey: 'policies.native.visibleExcept.title', summaryKey: 'policies.native.visibleExcept.summary', helpKey: 'policies.native.visibleExcept.help', audienceKey: 'policies.audience.whoCannotSee', compatibility: RESOURCE_TARGETS, access: ['VIEW'], audienceMode: 'EXCLUDE' },
  { id: 'write_only', family: 'WRITING', titleKey: 'policies.native.writeOnly.title', summaryKey: 'policies.native.writeOnly.summary', helpKey: 'policies.native.writeOnly.help', audienceKey: 'policies.audience.whoCanWrite', compatibility: RESOURCE_TARGETS, access: ['WRITE'], audienceMode: 'INCLUDE' },
  { id: 'write_except', family: 'WRITING', titleKey: 'policies.native.writeExcept.title', summaryKey: 'policies.native.writeExcept.summary', helpKey: 'policies.native.writeExcept.help', audienceKey: 'policies.audience.whoCannotWrite', compatibility: RESOURCE_TARGETS, access: ['WRITE'], audienceMode: 'EXCLUDE' },
  { id: 'open_read_limited_write', family: 'WRITING', titleKey: 'policies.native.openRead.title', summaryKey: 'policies.native.openRead.summary', helpKey: 'policies.native.openRead.help', audienceKey: 'policies.audience.whoCanPublish', compatibility: RESOURCE_TARGETS, access: ['VIEW', 'WRITE'], audienceMode: 'INCLUDE' },
  { id: 'private_space', family: 'VISIBILITY', titleKey: 'policies.native.private.title', summaryKey: 'policies.native.private.summary', helpKey: 'policies.native.private.help', audienceKey: 'policies.audience.whoCanSee', compatibility: ['LOGICAL_GROUP', 'CATEGORY', 'TEXT_CHANNEL'], access: ['VIEW'], audienceMode: 'INCLUDE' },
  { id: 'staff_only', family: 'AUDIENCE', titleKey: 'policies.native.staff.title', summaryKey: 'policies.native.staff.summary', helpKey: 'policies.native.staff.help', audienceKey: 'policies.audience.whichStaff', compatibility: ['GUILD', 'LOGICAL_GROUP', 'CATEGORY', 'TEXT_CHANNEL', 'VOICE_CHANNEL'], access: ['VIEW'], audienceMode: 'INCLUDE', editorKind: 'NAMED_AUDIENCE', requiresNamedAudience: 'STAFF' },
  { id: 'confirmed_members_only', family: 'AUDIENCE', titleKey: 'policies.native.confirmedMembers.title', summaryKey: 'policies.native.confirmedMembers.summary', helpKey: 'policies.native.confirmedMembers.help', audienceKey: 'policies.audience.whichConfirmed', compatibility: RESOURCE_TARGETS, access: ['VIEW'], audienceMode: 'INCLUDE', editorKind: 'NAMED_AUDIENCE', requiresNamedAudience: 'CONFIRMED_MEMBER' },
  { id: 'at_least_one_role', family: 'ZONE', titleKey: 'policies.native.anyRole.title', summaryKey: 'policies.native.anyRole.summary', helpKey: 'policies.native.anyRole.help', audienceKey: 'policies.audience.anyOfTheseRoles', compatibility: RESOURCE_TARGETS, access: ['VIEW'], audienceMode: 'INCLUDE' },
  { id: 'all_roles_required', family: 'ZONE', titleKey: 'policies.native.allRoles.title', summaryKey: 'policies.native.allRoles.summary', helpKey: 'policies.native.allRoles.help', audienceKey: 'policies.audience.allOfTheseRoles', compatibility: RESOURCE_TARGETS, access: ['VIEW'], audienceMode: 'INCLUDE' },
  { id: 'role_but_not_role', family: 'ZONE', titleKey: 'policies.native.roleButNotRole.title', summaryKey: 'policies.native.roleButNotRole.summary', helpKey: 'policies.native.roleButNotRole.help', audienceKey: 'policies.audience.hasButNot', compatibility: RESOURCE_TARGETS, access: ['VIEW'], audienceMode: 'INCLUDE', editorKind: 'ROLE_BUT_NOT', wizardCompatible: false, matrixCompatible: false },
  { id: 'voice_join_no_speak', family: 'VOCAL', titleKey: 'policies.native.voiceJoinNoSpeak.title', summaryKey: 'policies.native.voiceJoinNoSpeak.summary', helpKey: 'policies.native.voiceJoinNoSpeak.help', audienceKey: 'policies.audience.whoCanJoinWithoutSpeaking', compatibility: ['VOICE_CHANNEL'], access: ['CONNECT', 'SPEAK'], audienceMode: 'INCLUDE' },
  { id: 'voice_speakers', family: 'VOCAL', titleKey: 'policies.native.voiceSpeakers.title', summaryKey: 'policies.native.voiceSpeakers.summary', helpKey: 'policies.native.voiceSpeakers.help', audienceKey: 'policies.audience.whoCanSpeak', compatibility: ['VOICE_CHANNEL'], access: ['CONNECT', 'SPEAK'], audienceMode: 'INCLUDE' },
  { id: 'private_voice', family: 'VOCAL', titleKey: 'policies.native.privateVoice.title', summaryKey: 'policies.native.privateVoice.summary', helpKey: 'policies.native.privateVoice.help', audienceKey: 'policies.audience.whoCanJoin', compatibility: ['VOICE_CHANNEL'], access: ['CONNECT'], audienceMode: 'INCLUDE' },
  { id: 'voice_managers', family: 'VOCAL', titleKey: 'policies.native.voiceManagers.title', summaryKey: 'policies.native.voiceManagers.summary', helpKey: 'policies.native.voiceManagers.help', audienceKey: 'policies.audience.whoManagesVoice', compatibility: ['VOICE_CHANNEL'], access: ['MANAGE_VOICE'], audienceMode: 'INCLUDE' },
  { id: 'thread_creators', family: 'THREADS', titleKey: 'policies.native.threadCreators.title', summaryKey: 'policies.native.threadCreators.summary', helpKey: 'policies.native.threadCreators.help', audienceKey: 'policies.audience.whoCreatesThreads', compatibility: ['TEXT_CHANNEL'], access: ['CREATE_THREAD'], audienceMode: 'INCLUDE' },
  { id: 'reactions', family: 'REACTIONS', titleKey: 'policies.native.reactions.title', summaryKey: 'policies.native.reactions.summary', helpKey: 'policies.native.reactions.help', audienceKey: 'policies.audience.reactionMode', compatibility: ['TEXT_CHANNEL'], access: ['REACT'], audienceMode: 'INCLUDE', editorKind: 'MODE', wizardCompatible: false },
  { id: 'mentions', family: 'MENTIONS', titleKey: 'policies.native.mentions.title', summaryKey: 'policies.native.mentions.summary', helpKey: 'policies.native.mentions.help', audienceKey: 'policies.audience.mentionMode', compatibility: ['GUILD', 'CATEGORY', 'TEXT_CHANNEL'], access: ['MENTION_EVERYONE_HERE'], audienceMode: 'INCLUDE', editorKind: 'MENTIONS', wizardCompatible: false },
  { id: 'bot_minimal', family: 'BOTS', titleKey: 'policies.native.botMinimal.title', summaryKey: 'policies.native.botMinimal.summary', helpKey: 'policies.native.botMinimal.help', audienceKey: 'policies.bot.select', compatibility: ['TEXT_CHANNEL', 'VOICE_CHANNEL'], access: [], audienceMode: 'INCLUDE', editorKind: 'BOT', wizardCompatible: false, matrixCompatible: false },
] as const

export type PolicyTarget = { kind: PolicyTargetKind; scopeType: PolicyScopeType; scopeId: string | null; label: string }

export type PolicyDraftDefinition = {
  policy_type: 'ACCESS_CONTROL'; contract_version: 1; name: string; description: string
  scope_type: PolicyScopeType; scope_id: string | null; priority: number
  conditions: PolicyCondition[]; effects: PolicyEffect[]
  metadata: { summary: string; tags: string[]; reason: string | null }
}

export type NativePolicyValues = {
  name: string; description: string; priority?: number; sourcePolicyId?: string
  reactionMode?: PolicyMode; threadMode?: PolicyMode
  includeStaff?: boolean; staffRoleIds?: readonly string[]
  botId?: string; botFunctions?: readonly BotFunction[]
  /** REQ-AP-ZONE-060/061: "A mais pas B" -- roleIds is A, excludedRoleIds is B. */
  excludedRoleIds?: readonly string[]
}

export function compatibleNativePolicies(kind: PolicyTargetKind | null): readonly NativePolicy[] {
  if (!kind) return nativePolicies
  return nativePolicies.filter((policy) => policy.compatibility.includes(kind))
}

export function policyTargetKind(policy: Policy, channelType?: number): PolicyTargetKind {
  if (policy.scope_type !== 'CHANNEL') return policy.scope_type as Exclude<PolicyTargetKind, 'TEXT_CHANNEL' | 'VOICE_CHANNEL'>
  return channelType === 2 || channelType === 13 ? 'VOICE_CHANNEL' : 'TEXT_CHANNEL'
}

export function isPolicyCompatible(policy: Policy, target: PolicyTarget | null, channelTypes: ReadonlyMap<string, number>): boolean {
  if (!target) return true
  if (policy.scope_type === 'CHANNEL' && target.scopeType === 'CHANNEL') {
    const accesses = policy.effects.map((effect) => effect.access)
    const policyVoice = accesses.some((access) => access === 'CONNECT' || access === 'SPEAK' || access === 'MANAGE_VOICE')
    const targetVoice = target.kind === 'VOICE_CHANNEL'
    return policyVoice === targetVoice || (!policyVoice && !targetVoice)
  }
  const existingKind = policyTargetKind(policy, policy.scope_id ? channelTypes.get(policy.scope_id) : undefined)
  return existingKind === target.kind
}

export function nativePolicyByTag(policy: Policy): NativePolicy | undefined {
  const tag = policy.metadata.tags.find((value) => value.startsWith('did-native:'))
  return nativePolicies.find((native) => `did-native:${native.id}` === tag)
}

function audience(roleIds: readonly string[], mode: 'INCLUDE' | 'EXCLUDE', match: 'ANY' | 'ALL' = 'ANY') {
  return { mode, match, role_ids: [...new Set(roleIds)] }
}

function whitelist(access: PolicyAccess, roleIds: readonly string[]): PolicyEffect[] {
  return [
    { kind: 'SET_ACCESS', access, decision: 'ALLOW', audience: audience(roleIds, 'INCLUDE') },
    { kind: 'SET_ACCESS', access, decision: 'DENY', audience: audience(roleIds, 'EXCLUDE') },
  ]
}

function modeEffects(access: PolicyAccess, mode: PolicyMode, roleIds: readonly string[]): PolicyEffect[] {
  if (mode === 'INHERIT') return []
  if (mode === 'EVERYONE') return [{ kind: 'SET_ACCESS', access, decision: 'ALLOW' }]
  if (mode === 'NONE') return [{ kind: 'SET_ACCESS', access, decision: 'DENY' }]
  return whitelist(access, roleIds)
}

function botEffects(functions: readonly BotFunction[]): PolicyEffect[] {
  const accesses: PolicyAccess[] = functions.length ? ['VIEW'] : []
  for (const value of functions) {
    if (value === 'READ') accesses.push('READ_HISTORY')
    if (value === 'WRITE') accesses.push('SEND')
    if (value === 'MANAGE') accesses.push('MANAGE_CHANNEL')
    if (value === 'THREADS') accesses.push('CREATE_THREAD', 'PARTICIPATE_THREAD')
    if (value === 'VOCAL') accesses.push('CONNECT', 'SPEAK')
  }
  return [...new Set(accesses)].map((access) => ({ kind: 'SET_ACCESS', access, decision: 'ALLOW' }))
}

export function createDefinitionFromNative(
  native: NativePolicy,
  target: PolicyTarget,
  roleIds: readonly string[],
  values: NativePolicyValues,
): PolicyDraftDefinition {
  let conditions: PolicyCondition[] = [{ kind: 'ALWAYS' }]
  let effects: PolicyEffect[]
  const selectedAudience = audience(roleIds, native.audienceMode)
  if (native.id === 'voice_join_no_speak') {
    effects = [
      { kind: 'SET_ACCESS', access: 'CONNECT', decision: 'ALLOW', audience: selectedAudience },
      { kind: 'SET_ACCESS', access: 'SPEAK', decision: 'DENY', audience: selectedAudience },
    ]
  } else if (native.id === 'voice_speakers') {
    effects = [{ kind: 'SET_ACCESS', access: 'CONNECT', decision: 'ALLOW' }, ...whitelist('SPEAK', roleIds)]
  } else if (native.id === 'private_voice') {
    const joined = [...new Set([...roleIds, ...(values.includeStaff ? values.staffRoleIds ?? [] : [])])]
    effects = whitelist('CONNECT', joined)
  } else if (native.id === 'voice_managers') {
    effects = whitelist('MANAGE_VOICE', roleIds)
  } else if (native.id === 'thread_creators') {
    effects = whitelist('CREATE_THREAD', roleIds)
  } else if (native.id === 'reactions') {
    effects = modeEffects('REACT', values.reactionMode ?? 'ONLY', roleIds)
  } else if (native.id === 'mentions') {
    effects = modeEffects('MENTION_EVERYONE_HERE', values.reactionMode ?? 'ONLY', roleIds)
  } else if (native.id === 'bot_minimal') {
    conditions = values.botId ? [{ kind: 'BOT_MATCH', bot_user_ids: [values.botId] }] : []
    effects = botEffects(values.botFunctions ?? [])
  } else if (native.id === 'all_roles_required') {
    effects = native.access.map((access) => ({ kind: 'SET_ACCESS', access, decision: 'ALLOW', audience: audience(roleIds, 'INCLUDE', 'ALL') }))
  } else if (native.id === 'role_but_not_role') {
    const excluded = values.excludedRoleIds ?? []
    conditions = [
      { kind: 'ROLE_MATCH', match: 'ANY', role_ids: [...new Set(roleIds)] },
      ...(excluded.length ? [{ kind: 'ROLE_EXCLUDE' as const, match: 'ANY' as const, role_ids: [...new Set(excluded)] }] : []),
    ]
    effects = native.access.map((access) => ({ kind: 'SET_ACCESS', access, decision: 'ALLOW' }))
  } else {
    effects = native.access.map((access) => ({
      kind: 'SET_ACCESS', access, decision: 'ALLOW',
      ...(native.id === 'open_read_limited_write' && access === 'VIEW' ? {} : { audience: selectedAudience }),
    }))
    if (native.id === 'staff_only' && target.kind === 'VOICE_CHANNEL') effects.push({ kind: 'SET_ACCESS', access: 'CONNECT', decision: 'ALLOW', audience: selectedAudience })
    if (native.id === 'open_read_limited_write') {
      effects.push(...modeEffects('REACT', values.reactionMode ?? 'INHERIT', roleIds))
      effects.push(...modeEffects('CREATE_THREAD', values.threadMode ?? 'INHERIT', roleIds))
    }
  }
  const tags = [`did-native:${native.id}`, `audience:${native.audienceMode.toLowerCase()}`]
  if (values.reactionMode) tags.push(`reaction-mode:${values.reactionMode.toLowerCase()}`)
  if (values.threadMode) tags.push(`thread-mode:${values.threadMode.toLowerCase()}`)
  if (values.includeStaff) tags.push('staff-explicit:true')
  if (native.id === 'bot_minimal' && values.botFunctions?.length) tags.push(`bot-functions:${values.botFunctions.map((value) => value.toLowerCase()).join(',')}`)
  if (values.sourcePolicyId) tags.push(`source-policy:${values.sourcePolicyId}`)
  return {
    policy_type: 'ACCESS_CONTROL', contract_version: 1,
    name: values.name.trim(), description: values.description.trim(),
    scope_type: target.scopeType, scope_id: target.scopeId, priority: values.priority ?? 0,
    conditions, effects,
    metadata: { summary: values.description.trim() || values.name.trim(), tags, reason: null },
  }
}

// REQ-AP-ZONE-030..032: "visible to members not yet confirmed, optionally
// including staff". The OR between "not confirmed" and "is staff" cannot be
// expressed inside one Policy's (implicitly ANDed) conditions tuple -- the
// resolver already composes independent Policies with the same ALLOW
// decision (see PolicyResolver._maximal), so this is two Policies sharing a
// `newcomer-area:<id>` tag, not a new engine capability.
export function createNewcomerAreaDefinitions(
  target: PolicyTarget,
  confirmedMemberRoleIds: readonly string[],
  values: NativePolicyValues & { includeStaffRoleIds?: readonly string[] },
): PolicyDraftDefinition[] {
  const groupId = crypto.randomUUID()
  const base: PolicyDraftDefinition = {
    policy_type: 'ACCESS_CONTROL', contract_version: 1,
    name: values.name.trim(), description: values.description.trim(),
    scope_type: target.scopeType, scope_id: target.scopeId, priority: values.priority ?? 0,
    conditions: [{ kind: 'ROLE_EXCLUDE', match: 'ANY', role_ids: [...new Set(confirmedMemberRoleIds)] }],
    effects: [{ kind: 'SET_ACCESS', access: 'VIEW', decision: 'ALLOW' }],
    metadata: { summary: values.description.trim() || values.name.trim(), tags: ['did-native:newcomer_area', `newcomer-area:${groupId}`, 'newcomer-area:base'], reason: null },
  }
  const staffRoleIds = values.includeStaffRoleIds ?? []
  if (!staffRoleIds.length) return [base]
  const staffLayer: PolicyDraftDefinition = {
    ...base,
    name: `${base.name} (Staff)`,
    conditions: [{ kind: 'ALWAYS' }],
    effects: [{ kind: 'SET_ACCESS', access: 'VIEW', decision: 'ALLOW', audience: audience(staffRoleIds, 'INCLUDE') }],
    metadata: { ...base.metadata, tags: ['did-native:newcomer_area', `newcomer-area:${groupId}`, 'newcomer-area:staff'] },
  }
  return [base, staffLayer]
}

export function clonePolicyDefinition(policy: Policy, name: string): PolicyDraftDefinition {
  const tags = policy.metadata.tags.filter((tag) => !tag.startsWith('source-policy:'))
  tags.push(`source-policy:${policy.policy_id}`)
  return {
    policy_type: 'ACCESS_CONTROL', contract_version: 1,
    name: name.trim(), description: policy.description,
    scope_type: policy.scope_type, scope_id: policy.scope_id, priority: policy.priority,
    conditions: policy.conditions, effects: policy.effects,
    metadata: { ...policy.metadata, tags },
  }
}
