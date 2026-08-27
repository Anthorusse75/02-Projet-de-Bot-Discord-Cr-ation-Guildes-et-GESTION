import { QueryClient } from '@tanstack/react-query'
import { discordSnowflake } from '../../shared/discord-id'
import { useInteractionStore } from '../../shared/state/interaction'
import { leaveTenant, tenantSignal } from '../../api/tenantLifecycle'
import { queryKeys } from '../../api/queryKeys'
import { resolveGuildEvent } from '../../api/useGuildSocket'
import { resolveActions, type ActionContext, type ResourceRef } from './actions'
import { resolveDropTarget } from './dropTarget'
import { DRAG_THRESHOLDS, PointerGestureManager } from './gestures'

const guildA = discordSnowflake('100000000000000001')
const guildB = discordSnowflake('100000000000000002')
const channel: ResourceRef = { id: 'c1', name: 'general', type: 'CHANNEL', guildId: guildA }
const categoryA: ResourceRef = { id: 'ca', name: 'A', type: 'CATEGORY', guildId: guildA }
const categoryB: ResourceRef = { id: 'cb', name: 'B', type: 'CATEGORY', guildId: guildB }
const context = (source = [channel], destination?: ResourceRef): ActionContext => ({
  source, ...(destination ? { destination } : {}),
  userCapabilities: new Set(['STRUCTURE_READ', 'STRUCTURE_WRITE', 'PLANS_CREATE', 'PERMISSIONS_READ']),
  botCapabilities: new Set(['MANAGE_CHANNEL']),
})

describe('STAGE 07 shared interaction model', () => {
  it('filters actions by cardinality, capability and tenant mode', () => {
    expect(resolveActions(context()).map((item) => item.action.id)).toContain('open')
    expect(resolveActions(context([channel, { ...channel, id: 'c2' }])).map((item) => item.action.id)).toContain('bulk')
    expect(resolveDropTarget(context([channel], categoryA)).actions.map((item) => item.action.id)).toContain('move')
    const cross = resolveDropTarget(context([channel], categoryB))
    expect(cross.crossGuild).toBe(true)
    expect(cross.actions.map((item) => item.action.id)).toContain('copy')
  })

  it('distinguishes right click, right drag, left drag and cancellation at deterministic thresholds', () => {
    expect(DRAG_THRESHOLDS).toEqual({ mouse: 6, pen: 8, touch: 12 })
    const manager = new PointerGestureManager()
    manager.start({ pointerId: 1, button: 2, pointerType: 'mouse', clientX: 0, clientY: 0 }, channel)
    expect(manager.finish({ pointerId: 1, clientX: 2, clientY: 2 })?.kind).toBe('context')
    manager.start({ pointerId: 2, button: 2, pointerType: 'mouse', clientX: 0, clientY: 0 }, channel)
    expect(manager.move({ pointerId: 2, clientX: 6, clientY: 0 })).toBe(true)
    expect(manager.finish({ pointerId: 2, clientX: 6, clientY: 0 })?.kind).toBe('right-drag')
    manager.start({ pointerId: 3, button: 0, pointerType: 'touch', clientX: 0, clientY: 0 }, channel)
    expect(manager.move({ pointerId: 3, clientX: 11, clientY: 0 })).toBe(false)
    expect(manager.cancel()?.kind).toBe('cancel')
  })

  it('aborts and purges only the departed tenant namespace', async () => {
    const client = new QueryClient()
    const user = discordSnowflake('100000000000000003')
    client.setQueryData(queryKeys.tenant(user, guildA, 'structure'), { guild: 'A' })
    client.setQueryData(queryKeys.tenant(user, guildB, 'structure'), { guild: 'B' })
    const signal = tenantSignal(guildA)
    useInteractionStore.getState().setSelection([channel])
    await leaveTenant(client, user, guildA)
    expect(signal.aborted).toBe(true)
    expect(client.getQueryData(queryKeys.tenant(user, guildA, 'structure'))).toBeUndefined()
    expect(client.getQueryData(queryKeys.tenant(user, guildB, 'structure'))).toEqual({ guild: 'B' })
    expect(useInteractionStore.getState().selection).toEqual([])
  })

  it('ignores foreign/versioned socket events and invalidates fully on a sequence gap', () => {
    expect(resolveGuildEvent({ guild_id: guildB, sequence: 2, version: 1 }, guildA, 1).kind).toBe('ignore')
    expect(resolveGuildEvent({ guild_id: guildA, sequence: 2, version: 2 }, guildA, 1).kind).toBe('ignore')
    expect(resolveGuildEvent({ guild_id: guildA, sequence: 3, version: 1 }, guildA, 1).kind).toBe('full')
    expect(resolveGuildEvent({ guild_id: guildA, sequence: 2, version: 1, type: 'plan.updated' }, guildA, 1)).toMatchObject({ kind: 'feature', feature: 'plans' })
  })

  it('resolves a large action matrix within the dashboard interaction budget', () => {
    const started = performance.now()
    for (let index = 0; index < 20_000; index += 1) resolveActions(context([channel], index % 2 ? categoryA : categoryB))
    expect(performance.now() - started).toBeLessThan(500)
  })
})
