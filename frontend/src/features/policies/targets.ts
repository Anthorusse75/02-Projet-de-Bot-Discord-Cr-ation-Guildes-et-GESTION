import type { Guild, LogicalGroup, Role, Structure } from '../../api/types'
import type { PolicyTarget } from './catalog'

export function targetKey(target: PolicyTarget): string {
  return `${target.kind}:${target.scopeId ?? '*'}`
}

/**
 * Builds the read-model-derived list of policy targets (guild, logical groups, categories,
 * channels, roles) for the current tenant. Shared by the Policies workspace and by any Wizard
 * step that needs to offer the same real, existing targets (REQ-WIZ-004).
 */
export function buildPolicyTargets(guild: Guild, roles: readonly Role[], groups: readonly LogicalGroup[] | undefined, structure: Structure | undefined): PolicyTarget[] {
  const values: PolicyTarget[] = [{ kind: 'GUILD', scopeType: 'GUILD', scopeId: null, label: guild.name }]
  for (const group of groups ?? []) values.push({ kind: 'LOGICAL_GROUP', scopeType: 'LOGICAL_GROUP', scopeId: group.id, label: group.name })
  for (const category of structure?.categories ?? []) {
    values.push({ kind: 'CATEGORY', scopeType: 'CATEGORY', scopeId: category.id, label: category.name })
    for (const channel of category.channels) values.push({ kind: channel.type === 2 || channel.type === 13 ? 'VOICE_CHANNEL' : 'TEXT_CHANNEL', scopeType: 'CHANNEL', scopeId: channel.id, label: `${category.name} / ${channel.name}` })
  }
  for (const channel of structure?.root_channels ?? []) values.push({ kind: channel.type === 2 || channel.type === 13 ? 'VOICE_CHANNEL' : 'TEXT_CHANNEL', scopeType: 'CHANNEL', scopeId: channel.id, label: channel.name })
  for (const role of roles) values.push({ kind: 'ROLE', scopeType: 'ROLE', scopeId: role.id, label: role.name })
  return values
}
