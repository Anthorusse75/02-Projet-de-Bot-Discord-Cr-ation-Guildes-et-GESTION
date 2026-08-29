import type { MessageKey } from '../../localization/catalog'
import type { CapabilityDecision, CapabilityOutcome } from '../../api/types'
import type { DiscordSnowflake } from '../../shared/discord-id'

export type ResourceType = 'GUILD' | 'CATEGORY' | 'CHANNEL' | 'THREAD' | 'ROLE' | 'ARTIFACT' | 'TEMPLATE' | 'TRANSLATION_GROUP' | 'LANGUAGE_TARGET'
export type ResourceRef = { id: string; name: string; type: ResourceType; guildId: DiscordSnowflake; position?: number; parentId?: string | null; channelType?: number }
export type ActionContext = {
  source: ResourceRef[]
  destination?: ResourceRef
  sourceUserCapabilities: Readonly<Record<string, CapabilityDecision | undefined>>
  sourceBotCapabilities: Readonly<Record<string, CapabilityDecision | undefined>>
  destinationUserCapabilities?: Readonly<Record<string, CapabilityDecision | undefined>>
  destinationBotCapabilities?: Readonly<Record<string, CapabilityDecision | undefined>>
  destinationInstallationStatus?: string | null
  providerCapabilities?: Readonly<Record<string, CapabilityDecision | undefined>>
}
export type ActionId = 'open' | 'move' | 'copy' | 'clone' | 'export' | 'explain' | 'bulk' | 'CREATE_VARIANT' | 'LINK_EXISTING_VARIANT' | 'CLONE_UNLINKED' | 'PREVIEW'
export type AppAction = {
  id: ActionId
  sourceTypes: readonly ResourceType[]
  min: number
  max: number
  targetTypes?: readonly ResourceType[]
  requiresTarget?: boolean
  guildMode: 'ANY' | 'SAME' | 'CROSS'
  sourceUserCapabilities?: readonly string[]
  sourceBotCapabilities?: readonly string[]
  destinationUserCapabilities?: readonly string[]
  destinationBotCapabilities?: readonly string[]
  providerCapabilities?: readonly string[]
  risk: 'LOW' | 'MEDIUM' | 'HIGH'
  labelKey: MessageKey
  descriptionKey: MessageKey
  tooltipKey: MessageKey
  intention: 'READ' | 'PLAN' | 'PORTABLE_EXPORT' | 'PORTABLE_CLONE'
}

export const actions: readonly AppAction[] = [
  { id: 'open', sourceTypes: ['GUILD','CATEGORY','CHANNEL','THREAD','ROLE','ARTIFACT','TEMPLATE'], min: 1, max: 1, guildMode: 'ANY', risk: 'LOW', labelKey: 'actions.open', descriptionKey: 'actions.open.description', tooltipKey: 'actions.open.tooltip', intention: 'READ' },
  { id: 'move', sourceTypes: ['CATEGORY','CHANNEL'], targetTypes: ['GUILD','CATEGORY'], requiresTarget: true, min: 1, max: 100, guildMode: 'SAME', sourceUserCapabilities: ['plans.create','structure.write'], sourceBotCapabilities: ['REORDER_CHANNELS'], risk: 'MEDIUM', labelKey: 'actions.move', descriptionKey: 'actions.move.description', tooltipKey: 'actions.move.tooltip', intention: 'PLAN' },
  { id: 'copy', sourceTypes: ['CATEGORY','CHANNEL'], targetTypes: ['GUILD','CATEGORY'], requiresTarget: true, min: 1, max: 100, guildMode: 'CROSS', sourceUserCapabilities: ['structure.read'], destinationUserCapabilities: ['plans.create','structure.write'], destinationBotCapabilities: ['CREATE_CHANNEL'], risk: 'MEDIUM', labelKey: 'actions.copy', descriptionKey: 'actions.copy.description', tooltipKey: 'actions.copy.tooltip', intention: 'PORTABLE_CLONE' },
  { id: 'clone', sourceTypes: ['CATEGORY','CHANNEL','ARTIFACT','TEMPLATE'], targetTypes: ['GUILD','CATEGORY'], requiresTarget: true, min: 1, max: 1, guildMode: 'ANY', sourceUserCapabilities: ['structure.read'], destinationUserCapabilities: ['plans.create','structure.write'], destinationBotCapabilities: ['CREATE_CHANNEL'], risk: 'MEDIUM', labelKey: 'actions.clone', descriptionKey: 'actions.clone.description', tooltipKey: 'actions.clone.tooltip', intention: 'PORTABLE_CLONE' },
  { id: 'export', sourceTypes: ['CATEGORY','CHANNEL'], min: 1, max: 100, guildMode: 'ANY', sourceUserCapabilities: ['structure.read'], risk: 'LOW', labelKey: 'actions.export', descriptionKey: 'actions.export.description', tooltipKey: 'actions.export.tooltip', intention: 'PORTABLE_EXPORT' },
  { id: 'explain', sourceTypes: ['CHANNEL','THREAD','ROLE'], min: 1, max: 1, guildMode: 'ANY', sourceUserCapabilities: ['permissions.read'], risk: 'LOW', labelKey: 'actions.explain', descriptionKey: 'actions.explain.description', tooltipKey: 'actions.explain.tooltip', intention: 'READ' },
  { id: 'bulk', sourceTypes: ['CHANNEL'], targetTypes: ['CATEGORY'], requiresTarget: true, min: 2, max: 100, guildMode: 'SAME', sourceUserCapabilities: ['plans.create','structure.write'], sourceBotCapabilities: ['REORDER_CHANNELS'], risk: 'MEDIUM', labelKey: 'actions.bulk', descriptionKey: 'actions.bulk.description', tooltipKey: 'actions.bulk.tooltip', intention: 'PLAN' },
  { id: 'CREATE_VARIANT', sourceTypes: ['TRANSLATION_GROUP','LANGUAGE_TARGET'], min: 1, max: 1, guildMode: 'SAME', sourceUserCapabilities: ['plans.create','structure.write'], sourceBotCapabilities: ['CREATE_CHANNEL'], providerCapabilities: ['ROUTING_SUPPORTED'], risk: 'MEDIUM', labelKey: 'actions.createVariant', descriptionKey: 'actions.createVariant.description', tooltipKey: 'actions.createVariant.tooltip', intention: 'PLAN' },
  { id: 'LINK_EXISTING_VARIANT', sourceTypes: ['TRANSLATION_GROUP','LANGUAGE_TARGET'], min: 1, max: 1, guildMode: 'SAME', sourceUserCapabilities: ['plans.create','structure.write'], risk: 'MEDIUM', labelKey: 'actions.linkVariant', descriptionKey: 'actions.linkVariant.description', tooltipKey: 'actions.linkVariant.tooltip', intention: 'PLAN' },
  { id: 'CLONE_UNLINKED', sourceTypes: ['TRANSLATION_GROUP'], min: 1, max: 100, guildMode: 'ANY', sourceUserCapabilities: ['structure.read'], risk: 'MEDIUM', labelKey: 'actions.cloneUnlinked', descriptionKey: 'actions.cloneUnlinked.description', tooltipKey: 'actions.cloneUnlinked.tooltip', intention: 'PORTABLE_CLONE' },
  { id: 'PREVIEW', sourceTypes: ['TRANSLATION_GROUP','LANGUAGE_TARGET'], min: 1, max: 100, guildMode: 'ANY', sourceUserCapabilities: ['structure.read'], risk: 'LOW', labelKey: 'actions.translationPreview', descriptionKey: 'actions.translationPreview.description', tooltipKey: 'actions.translationPreview.tooltip', intention: 'READ' },
] as const

export type Availability = { action: AppAction; enabled: boolean; reasonKey?: MessageKey }

function outcome(required: readonly string[] | undefined, available: Readonly<Record<string, CapabilityDecision | undefined>> | undefined): CapabilityOutcome {
  if (!required?.length) return 'CAN'
  const values = required.map((capability) => available?.[capability]?.outcome ?? 'UNKNOWN')
  if (values.includes('CANNOT')) return 'CANNOT'
  return values.every((value) => value === 'CAN') ? 'CAN' : 'UNKNOWN'
}

export function resolveActions(context: ActionContext): Availability[] {
  const sourceType = context.source[0]?.type
  if (!sourceType || context.source.some((item) => item.type !== sourceType)) return []
  return actions.flatMap((action) => {
    if (!action.sourceTypes.includes(sourceType) || context.source.length < action.min || context.source.length > action.max) return []
    if (context.destination && !action.targetTypes?.includes(context.destination.type)) return []
    const cross = Boolean(context.destination && context.source.some((item) => item.guildId !== context.destination?.guildId))
    if ((action.guildMode === 'CROSS' && context.destination && !cross) || (action.guildMode === 'SAME' && cross)) return []
    const checks: CapabilityOutcome[] = [
      outcome(action.sourceUserCapabilities, context.sourceUserCapabilities),
      outcome(action.sourceBotCapabilities, context.sourceBotCapabilities),
      outcome(action.providerCapabilities, context.providerCapabilities),
    ]
    if (context.destination) {
      const destinationUser = cross ? context.destinationUserCapabilities : context.destinationUserCapabilities ?? context.sourceUserCapabilities
      const destinationBot = cross ? context.destinationBotCapabilities : context.destinationBotCapabilities ?? context.sourceBotCapabilities
      checks.push(outcome(action.destinationUserCapabilities, destinationUser), outcome(action.destinationBotCapabilities, destinationBot))
      if (cross && action.destinationUserCapabilities?.length && context.destinationInstallationStatus !== 'ACTIVE') checks.push(context.destinationInstallationStatus ? 'CANNOT' : 'UNKNOWN')
    }
    const enabled = checks.every((value) => value === 'CAN')
    return [enabled
      ? { action, enabled: true }
      : { action, enabled: false, reasonKey: checks.includes('CANNOT') ? 'actions.disabled.capability' : 'actions.disabled.unknown' }]
  })
}
