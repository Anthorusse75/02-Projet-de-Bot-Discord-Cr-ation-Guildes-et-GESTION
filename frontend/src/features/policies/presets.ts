import type { PolicyCondition, PolicyEffect } from '../../api/types'
import { modeEffects, whitelist, type PolicyDraftDefinition, type PolicyMode, type PolicyTarget, type PolicyTargetKind } from './catalog'

// A preset (REQ-AP-PRS-*) is a guided composition of ALREADY EXISTING native
// building blocks (visibility/writing whitelist, mention control, reaction
// and thread mode) into several independent DRAFT Policies sharing one tag
// group -- the exact same pattern as createNewcomerAreaDefinitions(). No new
// PolicyResolver capability, no opaque alias: every sub-rule a preset
// activates is a real, inspectable Policy the admin can see individually in
// "Custom policies" once created, and the UI must show every sub-rule before
// any of them is created (REQ-AP-PRS-001).
//
// REQ-AP-PRS-022 (ticket engine integration for "Zone support") is not
// attempted: this product has no ticket engine anywhere, so the option
// would be a fake control with nothing behind it.

export type PresetId = 'confidential' | 'announcement_channel' | 'support_zone'

export type PresetCatalogEntry = {
  id: PresetId
  titleKey: string
  summaryKey: string
  helpKey: string
  compatibility: readonly PolicyTargetKind[]
}

const RESOURCE_TARGETS: readonly PolicyTargetKind[] = ['CATEGORY', 'TEXT_CHANNEL', 'VOICE_CHANNEL']

export const presets: readonly PresetCatalogEntry[] = [
  { id: 'confidential', titleKey: 'policies.preset.confidential.title', summaryKey: 'policies.preset.confidential.summary', helpKey: 'policies.preset.confidential.help', compatibility: RESOURCE_TARGETS },
  { id: 'announcement_channel', titleKey: 'policies.preset.announcement.title', summaryKey: 'policies.preset.announcement.summary', helpKey: 'policies.preset.announcement.help', compatibility: ['TEXT_CHANNEL'] },
  { id: 'support_zone', titleKey: 'policies.preset.supportZone.title', summaryKey: 'policies.preset.supportZone.summary', helpKey: 'policies.preset.supportZone.help', compatibility: ['CATEGORY', 'TEXT_CHANNEL'] },
] as const

export function compatiblePresets(kind: PolicyTargetKind | null): readonly PresetCatalogEntry[] {
  return kind ? presets.filter((preset) => preset.compatibility.includes(kind)) : []
}

export type PresetSubRule = { key: string; labelKey: string; roleIds?: readonly string[] }

// --- Confidentiel (REQ-AP-PRS-001) ---------------------------------------

export type ConfidentialConfig = { viewerRoleIds: readonly string[]; managerRoleIds: readonly string[]; blockMentions: boolean; restrictThreads: boolean }

export const emptyConfidentialConfig = (): ConfidentialConfig => ({ viewerRoleIds: [], managerRoleIds: [], blockMentions: true, restrictThreads: true })

export function confidentialSubRules(config: ConfidentialConfig): PresetSubRule[] {
  const rules: PresetSubRule[] = []
  if (config.viewerRoleIds.length) rules.push({ key: 'visibility', labelKey: 'policies.preset.confidential.rule.visibility', roleIds: config.viewerRoleIds })
  if (config.managerRoleIds.length) rules.push({ key: 'management', labelKey: 'policies.preset.confidential.rule.management', roleIds: config.managerRoleIds })
  if (config.blockMentions) rules.push({ key: 'mentions', labelKey: 'policies.preset.confidential.rule.mentions' })
  if (config.restrictThreads && config.managerRoleIds.length) rules.push({ key: 'threads', labelKey: 'policies.preset.confidential.rule.threads', roleIds: config.managerRoleIds })
  return rules
}

export function createConfidentialDefinitions(target: PolicyTarget, name: string, description: string, config: ConfidentialConfig): PolicyDraftDefinition[] {
  const groupId = crypto.randomUUID()
  const trimmedName = name.trim()
  const trimmedDescription = description.trim()
  function part(suffixKey: string, conditions: PolicyCondition[], effects: PolicyEffect[], subTag: string): PolicyDraftDefinition {
    return {
      policy_type: 'ACCESS_CONTROL', contract_version: 1,
      name: `${trimmedName} (${suffixKey})`, description: trimmedDescription,
      scope_type: target.scopeType, scope_id: target.scopeId, priority: 0,
      conditions, effects,
      metadata: { summary: trimmedDescription || trimmedName, tags: ['did-preset:confidential', `preset-group:${groupId}`, subTag], reason: null },
    }
  }
  const definitions: PolicyDraftDefinition[] = []
  if (config.viewerRoleIds.length) definitions.push(part('Visibility', [{ kind: 'ALWAYS' }], whitelist('VIEW', config.viewerRoleIds), 'preset-part:visibility'))
  if (config.managerRoleIds.length) definitions.push(part('Management', [{ kind: 'ALWAYS' }], whitelist('MANAGE', config.managerRoleIds), 'preset-part:management'))
  if (config.blockMentions) definitions.push(part('Mentions', [{ kind: 'ALWAYS' }], [{ kind: 'SET_ACCESS', access: 'MENTION_EVERYONE_HERE', decision: 'DENY' }], 'preset-part:mentions'))
  if (config.restrictThreads && config.managerRoleIds.length) definitions.push(part('Threads', [{ kind: 'ALWAYS' }], whitelist('CREATE_THREAD', config.managerRoleIds), 'preset-part:threads'))
  return definitions
}

// --- Salon d'annonces (REQ-AP-PRS-010..013) ------------------------------
// REQ-AP-PRS-011: persistent by default -- this preset never creates a
// temporary anything, and REQ-AP-PRS-012 keeps visibility a fully separate,
// untouched concern. Writing, reactions and thread capabilities stay explicit.

export type AnnouncementConfig = { publisherRoleIds: readonly string[]; reactionMode: PolicyMode; threadMode: PolicyMode; replyMode: PolicyMode }

export const emptyAnnouncementConfig = (): AnnouncementConfig => ({ publisherRoleIds: [], reactionMode: 'INHERIT', threadMode: 'INHERIT', replyMode: 'INHERIT' })

export function announcementSubRules(config: AnnouncementConfig): PresetSubRule[] {
  const rules: PresetSubRule[] = []
  if (config.publisherRoleIds.length) rules.push({ key: 'writers', labelKey: 'policies.preset.announcement.rule.writers', roleIds: config.publisherRoleIds })
  if (config.reactionMode !== 'INHERIT' && (config.reactionMode !== 'ONLY' || config.publisherRoleIds.length)) rules.push({ key: 'reactions', labelKey: `policies.preset.announcement.rule.reactions.${config.reactionMode}`, roleIds: config.publisherRoleIds })
  if (config.threadMode !== 'INHERIT' && (config.threadMode !== 'ONLY' || config.publisherRoleIds.length)) rules.push({ key: 'threads', labelKey: `policies.preset.announcement.rule.threads.${config.threadMode}`, roleIds: config.publisherRoleIds })
  if (config.replyMode !== 'INHERIT' && (config.replyMode !== 'ONLY' || config.publisherRoleIds.length)) rules.push({ key: 'replies', labelKey: `policies.preset.announcement.rule.replies.${config.replyMode}`, roleIds: config.publisherRoleIds })
  return rules
}

export function createAnnouncementDefinitions(target: PolicyTarget, name: string, description: string, config: AnnouncementConfig): PolicyDraftDefinition[] {
  const groupId = crypto.randomUUID()
  const trimmedName = name.trim()
  const trimmedDescription = description.trim()
  function part(suffixKey: string, effects: PolicyEffect[], subTag: string): PolicyDraftDefinition {
    return {
      policy_type: 'ACCESS_CONTROL', contract_version: 1,
      name: `${trimmedName} (${suffixKey})`, description: trimmedDescription,
      scope_type: target.scopeType, scope_id: target.scopeId, priority: 0,
      conditions: [{ kind: 'ALWAYS' }], effects,
      metadata: { summary: trimmedDescription || trimmedName, tags: ['did-preset:announcement_channel', `preset-group:${groupId}`, subTag], reason: null },
    }
  }
  const definitions: PolicyDraftDefinition[] = []
  if (config.publisherRoleIds.length) definitions.push(part('Writers', whitelist('WRITE', config.publisherRoleIds), 'preset-part:writers'))
  if (config.reactionMode !== 'INHERIT' && (config.reactionMode !== 'ONLY' || config.publisherRoleIds.length)) definitions.push(part('Reactions', modeEffects('REACT', config.reactionMode, config.publisherRoleIds), 'preset-part:reactions'))
  if (config.threadMode !== 'INHERIT' && (config.threadMode !== 'ONLY' || config.publisherRoleIds.length)) definitions.push(part('Threads', modeEffects('CREATE_THREAD', config.threadMode, config.publisherRoleIds), 'preset-part:threads'))
  if (config.replyMode !== 'INHERIT' && (config.replyMode !== 'ONLY' || config.publisherRoleIds.length)) definitions.push(part('Thread replies', modeEffects('PARTICIPATE_THREAD', config.replyMode, config.publisherRoleIds), 'preset-part:thread-replies'))
  return definitions
}

// --- Zone support (REQ-AP-PRS-020/021) -----------------------------------

export type SupportZoneConfig = { supportRoleIds: readonly string[]; visibility: 'OPEN' | 'PRIVATE'; writeMode: 'EVERYONE' | 'SUPPORT_ONLY' }

export const emptySupportZoneConfig = (): SupportZoneConfig => ({ supportRoleIds: [], visibility: 'OPEN', writeMode: 'EVERYONE' })

export function supportZoneSubRules(config: SupportZoneConfig): PresetSubRule[] {
  const rules: PresetSubRule[] = []
  if (config.visibility === 'PRIVATE' && config.supportRoleIds.length) rules.push({ key: 'visibility', labelKey: 'policies.preset.supportZone.rule.visibilityPrivate', roleIds: config.supportRoleIds })
  else rules.push({ key: 'visibility', labelKey: 'policies.preset.supportZone.rule.visibilityOpen' })
  if (config.writeMode === 'SUPPORT_ONLY' && config.supportRoleIds.length) rules.push({ key: 'write', labelKey: 'policies.preset.supportZone.rule.writeSupportOnly', roleIds: config.supportRoleIds })
  else rules.push({ key: 'write', labelKey: 'policies.preset.supportZone.rule.writeEveryone' })
  return rules
}

export function createSupportZoneDefinitions(target: PolicyTarget, name: string, description: string, config: SupportZoneConfig): PolicyDraftDefinition[] {
  const groupId = crypto.randomUUID()
  const trimmedName = name.trim()
  const trimmedDescription = description.trim()
  function part(suffixKey: string, effects: PolicyEffect[], subTag: string): PolicyDraftDefinition {
    return {
      policy_type: 'ACCESS_CONTROL', contract_version: 1,
      name: `${trimmedName} (${suffixKey})`, description: trimmedDescription,
      scope_type: target.scopeType, scope_id: target.scopeId, priority: 0,
      conditions: [{ kind: 'ALWAYS' }], effects,
      metadata: { summary: trimmedDescription || trimmedName, tags: ['did-preset:support_zone', `preset-group:${groupId}`, subTag], reason: null },
    }
  }
  const definitions: PolicyDraftDefinition[] = []
  if (config.visibility === 'PRIVATE' && config.supportRoleIds.length) definitions.push(part('Visibility', whitelist('VIEW', config.supportRoleIds), 'preset-part:visibility'))
  if (config.writeMode === 'SUPPORT_ONLY' && config.supportRoleIds.length) definitions.push(part('Writers', whitelist('WRITE', config.supportRoleIds), 'preset-part:writers'))
  return definitions
}
