import type { MessageKey } from '../../localization/catalog'
import type { CapabilityDecision } from '../../api/types'
import type { DiscordSnowflake } from '../../shared/discord-id'

export type ResourceType = 'GUILD' | 'CATEGORY' | 'CHANNEL' | 'THREAD' | 'ROLE' | 'ARTIFACT' | 'TEMPLATE'
export type ResourceRef = { id: string; name: string; type: ResourceType; guildId: DiscordSnowflake; position?: number; parentId?: string | null; channelType?: number }
export type ActionContext = {
  source: ResourceRef[]
  destination?: ResourceRef
  userCapabilities: Readonly<Record<string, CapabilityDecision | undefined>>
  botCapabilities: Readonly<Record<string, CapabilityDecision | undefined>>
}
export type AppAction = {
  id: string
  sourceTypes: readonly ResourceType[]
  min: number
  max: number
  targetTypes?: readonly ResourceType[]
  guildMode: 'ANY' | 'SAME' | 'CROSS'
  userCapability?: string
  botCapability?: string
  risk: 'LOW' | 'MEDIUM' | 'HIGH'
  labelKey: MessageKey
  descriptionKey: MessageKey
  tooltipKey: MessageKey
  intention: 'READ' | 'PLAN' | 'PORTABLE_EXPORT' | 'PORTABLE_CLONE'
}

export const actions: readonly AppAction[] = [
  { id: 'open', sourceTypes: ['GUILD','CATEGORY','CHANNEL','THREAD','ROLE','ARTIFACT','TEMPLATE'], min: 1, max: 1, guildMode: 'ANY', risk: 'LOW', labelKey: 'actions.open', descriptionKey: 'actions.open.description', tooltipKey: 'actions.open.tooltip', intention: 'READ' },
  { id: 'move', sourceTypes: ['CATEGORY','CHANNEL'], targetTypes: ['GUILD','CATEGORY'], min: 1, max: 100, guildMode: 'SAME', userCapability: 'structure.write', botCapability: 'REORDER_CHANNELS', risk: 'MEDIUM', labelKey: 'actions.move', descriptionKey: 'actions.move.description', tooltipKey: 'actions.move.tooltip', intention: 'PLAN' },
  { id: 'copy', sourceTypes: ['CATEGORY','CHANNEL'], targetTypes: ['GUILD','CATEGORY'], min: 1, max: 100, guildMode: 'CROSS', userCapability: 'plans.create', botCapability: 'CREATE_CHANNEL', risk: 'MEDIUM', labelKey: 'actions.copy', descriptionKey: 'actions.copy.description', tooltipKey: 'actions.copy.tooltip', intention: 'PORTABLE_CLONE' },
  { id: 'clone', sourceTypes: ['CATEGORY','CHANNEL','ARTIFACT','TEMPLATE'], targetTypes: ['GUILD','CATEGORY'], min: 1, max: 1, guildMode: 'ANY', userCapability: 'plans.create', botCapability: 'CREATE_CHANNEL', risk: 'MEDIUM', labelKey: 'actions.clone', descriptionKey: 'actions.clone.description', tooltipKey: 'actions.clone.tooltip', intention: 'PORTABLE_CLONE' },
  { id: 'export', sourceTypes: ['CATEGORY','CHANNEL'], min: 1, max: 100, guildMode: 'ANY', userCapability: 'structure.read', risk: 'LOW', labelKey: 'actions.export', descriptionKey: 'actions.export.description', tooltipKey: 'actions.export.tooltip', intention: 'PORTABLE_EXPORT' },
  { id: 'explain', sourceTypes: ['CHANNEL','THREAD','ROLE'], min: 1, max: 1, guildMode: 'ANY', userCapability: 'permissions.read', risk: 'LOW', labelKey: 'actions.explain', descriptionKey: 'actions.explain.description', tooltipKey: 'actions.explain.tooltip', intention: 'READ' },
  { id: 'bulk', sourceTypes: ['CATEGORY','CHANNEL','ROLE'], min: 2, max: 100, guildMode: 'ANY', userCapability: 'plans.create', risk: 'MEDIUM', labelKey: 'actions.bulk', descriptionKey: 'actions.bulk.description', tooltipKey: 'actions.bulk.tooltip', intention: 'PLAN' },
] as const

export type Availability = { action: AppAction; enabled: boolean; reasonKey?: MessageKey }

export function resolveActions(context: ActionContext): Availability[] {
  const sourceType = context.source[0]?.type
  if (!sourceType || context.source.some((item) => item.type !== sourceType)) return []
  return actions.flatMap((action) => {
    if (!action.sourceTypes.includes(sourceType) || context.source.length < action.min || context.source.length > action.max) return []
    if (context.destination && (!action.targetTypes?.includes(context.destination.type))) return []
    const cross = context.destination && context.source.some((item) => item.guildId !== context.destination?.guildId)
    if ((action.guildMode === 'CROSS' && !cross) || (action.guildMode === 'SAME' && cross)) return []
    const userOutcome = action.userCapability ? context.userCapabilities[action.userCapability]?.outcome ?? 'UNKNOWN' : 'CAN'
    const botOutcome = action.botCapability ? context.botCapabilities[action.botCapability]?.outcome ?? 'UNKNOWN' : 'CAN'
    return [userOutcome === 'CAN' && botOutcome === 'CAN'
      ? { action, enabled: true }
      : { action, enabled: false, reasonKey: userOutcome === 'CANNOT' || botOutcome === 'CANNOT' ? 'actions.disabled.capability' : 'actions.disabled.unknown' }]
  })
}
