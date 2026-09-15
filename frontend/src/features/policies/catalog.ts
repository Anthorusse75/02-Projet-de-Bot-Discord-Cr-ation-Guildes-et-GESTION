import type { Policy, PolicyAccess, PolicyCondition, PolicyEffect, PolicyScopeType } from '../../api/types'

export type PolicyTargetKind = 'GUILD' | 'LOGICAL_GROUP' | 'CATEGORY' | 'TEXT_CHANNEL' | 'VOICE_CHANNEL' | 'ROLE'
export type NativePolicyId =
  | 'visible_only'
  | 'visible_except'
  | 'write_only'
  | 'write_except'
  | 'open_read_limited_write'
  | 'private_space'
  | 'staff_only'

export type NativePolicy = {
  id: NativePolicyId
  family: 'VISIBILITY' | 'WRITING' | 'AUDIENCE'
  titleKey: string
  summaryKey: string
  helpKey: string
  audienceKey: string
  compatibility: readonly PolicyTargetKind[]
  access: readonly PolicyAccess[]
  audienceMode: 'INCLUDE' | 'EXCLUDE'
}

const RESOURCE_TARGETS = ['GUILD', 'LOGICAL_GROUP', 'CATEGORY', 'TEXT_CHANNEL'] as const

export const nativePolicies: readonly NativePolicy[] = [
  { id: 'visible_only', family: 'VISIBILITY', titleKey: 'policies.native.visibleOnly.title', summaryKey: 'policies.native.visibleOnly.summary', helpKey: 'policies.native.visibleOnly.help', audienceKey: 'policies.audience.whoCanSee', compatibility: RESOURCE_TARGETS, access: ['VIEW'], audienceMode: 'INCLUDE' },
  { id: 'visible_except', family: 'VISIBILITY', titleKey: 'policies.native.visibleExcept.title', summaryKey: 'policies.native.visibleExcept.summary', helpKey: 'policies.native.visibleExcept.help', audienceKey: 'policies.audience.whoCannotSee', compatibility: RESOURCE_TARGETS, access: ['VIEW'], audienceMode: 'EXCLUDE' },
  { id: 'write_only', family: 'WRITING', titleKey: 'policies.native.writeOnly.title', summaryKey: 'policies.native.writeOnly.summary', helpKey: 'policies.native.writeOnly.help', audienceKey: 'policies.audience.whoCanWrite', compatibility: RESOURCE_TARGETS, access: ['WRITE'], audienceMode: 'INCLUDE' },
  { id: 'write_except', family: 'WRITING', titleKey: 'policies.native.writeExcept.title', summaryKey: 'policies.native.writeExcept.summary', helpKey: 'policies.native.writeExcept.help', audienceKey: 'policies.audience.whoCannotWrite', compatibility: RESOURCE_TARGETS, access: ['WRITE'], audienceMode: 'EXCLUDE' },
  { id: 'open_read_limited_write', family: 'WRITING', titleKey: 'policies.native.openRead.title', summaryKey: 'policies.native.openRead.summary', helpKey: 'policies.native.openRead.help', audienceKey: 'policies.audience.whoCanPublish', compatibility: RESOURCE_TARGETS, access: ['VIEW', 'WRITE'], audienceMode: 'INCLUDE' },
  { id: 'private_space', family: 'VISIBILITY', titleKey: 'policies.native.private.title', summaryKey: 'policies.native.private.summary', helpKey: 'policies.native.private.help', audienceKey: 'policies.audience.whoCanSee', compatibility: ['LOGICAL_GROUP', 'CATEGORY', 'TEXT_CHANNEL'], access: ['VIEW'], audienceMode: 'INCLUDE' },
  { id: 'staff_only', family: 'AUDIENCE', titleKey: 'policies.native.staff.title', summaryKey: 'policies.native.staff.summary', helpKey: 'policies.native.staff.help', audienceKey: 'policies.audience.whichStaff', compatibility: ['GUILD', 'LOGICAL_GROUP', 'CATEGORY', 'TEXT_CHANNEL', 'VOICE_CHANNEL'], access: ['VIEW'], audienceMode: 'INCLUDE' },
] as const

export type PolicyTarget = {
  kind: PolicyTargetKind
  scopeType: PolicyScopeType
  scopeId: string | null
  label: string
}

export type PolicyDraftDefinition = {
  policy_type: 'ACCESS_CONTROL'
  contract_version: 1
  name: string
  description: string
  scope_type: PolicyScopeType
  scope_id: string | null
  priority: number
  conditions: PolicyCondition[]
  effects: PolicyEffect[]
  metadata: { summary: string; tags: string[]; reason: string | null }
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
    const policyVoice = accesses.some((access) => access === 'CONNECT' || access === 'SPEAK')
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

export function createDefinitionFromNative(
  native: NativePolicy,
  target: PolicyTarget,
  roleIds: readonly string[],
  values: { name: string; description: string; priority?: number; sourcePolicyId?: string },
): PolicyDraftDefinition {
  const conditions: PolicyCondition[] = [{ kind: 'ALWAYS' }]
  const audience = { mode: native.audienceMode, match: 'ANY' as const, role_ids: [...new Set(roleIds)] }
  const effects: PolicyEffect[] = native.access.map((access) => ({
    kind: 'SET_ACCESS', access, decision: 'ALLOW',
    ...(native.id === 'open_read_limited_write' && access === 'VIEW' ? {} : { audience }),
  }))
  if (native.id === 'staff_only' && target.kind === 'VOICE_CHANNEL') {
    effects.push({ kind: 'SET_ACCESS', access: 'CONNECT', decision: 'ALLOW', audience })
  }
  const tags = [`did-native:${native.id}`, `audience:${native.audienceMode.toLowerCase()}`]
  if (values.sourcePolicyId) tags.push(`source-policy:${values.sourcePolicyId}`)
  return {
    policy_type: 'ACCESS_CONTROL',
    contract_version: 1,
    name: values.name.trim(),
    description: values.description.trim(),
    scope_type: target.scopeType,
    scope_id: target.scopeId,
    priority: values.priority ?? 0,
    conditions,
    effects,
    metadata: { summary: values.description.trim() || values.name.trim(), tags, reason: null },
  }
}

export function clonePolicyDefinition(policy: Policy, name: string): PolicyDraftDefinition {
  const tags = policy.metadata.tags.filter((tag) => !tag.startsWith('source-policy:'))
  tags.push(`source-policy:${policy.policy_id}`)
  return {
    policy_type: 'ACCESS_CONTROL',
    contract_version: 1,
    name: name.trim(),
    description: policy.description,
    scope_type: policy.scope_type,
    scope_id: policy.scope_id,
    priority: policy.priority,
    conditions: policy.conditions,
    effects: policy.effects,
    metadata: { ...policy.metadata, tags },
  }
}
