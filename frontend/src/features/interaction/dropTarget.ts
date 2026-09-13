import type { ActionContext } from './actions'
import { resolveActions } from './actions'

export type DropResolution = { valid: boolean; crossGuild: boolean; actions: ReturnType<typeof resolveActions> }

export function resolveDropTarget(context: ActionContext): DropResolution {
  const target = context.destination
  if (!target || !['GUILD', 'CATEGORY', 'CHANNEL'].includes(target.type)) return { valid: false, crossGuild: false, actions: [] }
  const source = context.source[0]
  if (!source || source.id === target.id) return { valid: false, crossGuild: false, actions: [] }
  const crossGuild = source.guildId !== target.guildId

  // Discord categories cannot contain categories. Same-Guild category -> category
  // is nevertheless a valid reorder target and is compiled as a position-only move.
  if (source.type === 'CATEGORY' && target.type === 'CATEGORY' && crossGuild) return { valid: false, crossGuild, actions: [] }
  if (source.type === 'CATEGORY' && target.type === 'CHANNEL') return { valid: false, crossGuild, actions: [] }
  if (source.type === 'THREAD') return { valid: false, crossGuild, actions: [] }

  const actions = resolveActions(context)
  return { valid: actions.some((item) => item.enabled), crossGuild, actions }
}
