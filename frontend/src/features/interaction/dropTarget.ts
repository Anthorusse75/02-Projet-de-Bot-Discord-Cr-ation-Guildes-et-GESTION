import type { ActionContext } from './actions'
import { resolveActions } from './actions'

export type DropResolution = { valid: boolean; crossGuild: boolean; actions: ReturnType<typeof resolveActions> }

export function resolveDropTarget(context: ActionContext): DropResolution {
  const target = context.destination
  if (!target || !['GUILD', 'CATEGORY'].includes(target.type)) return { valid: false, crossGuild: false, actions: [] }
  const source = context.source[0]
  if (!source || source.id === target.id) return { valid: false, crossGuild: false, actions: [] }
  if (source.type === 'CATEGORY' && target.type === 'CATEGORY') return { valid: false, crossGuild: source.guildId !== target.guildId, actions: [] }
  if (source.type === 'THREAD' && target.type !== 'CHANNEL') return { valid: false, crossGuild: source.guildId !== target.guildId, actions: [] }
  const actions = resolveActions(context)
  return { valid: actions.some((item) => item.enabled), crossGuild: source.guildId !== target.guildId, actions }
}
