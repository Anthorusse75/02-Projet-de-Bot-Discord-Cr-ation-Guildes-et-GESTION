import { QueryClient } from '@tanstack/react-query'
import { discordSnowflake } from '../../shared/discord-id'
import { useInteractionStore } from '../../shared/state/interaction'
import { leaveTenant, tenantSignal } from '../../api/tenantLifecycle'
import { queryKeys } from '../../api/queryKeys'
import { reconnectDelay, resolveGuildEvent } from '../../api/useGuildSocket'
import { actions, resolveActions, type ActionContext, type ResourceRef } from './actions'
import { resolveDropTarget } from './dropTarget'
import { DRAG_THRESHOLDS, PointerGestureManager } from './gestures'
import { createActionIntent, dispatchAction, exportBody, handledActionIds, transferBody } from './dispatcher'
import { useSessionStore } from '../../shared/state/session'

const guildA = discordSnowflake('100000000000000001')
const guildB = discordSnowflake('100000000000000002')
const decisionCan = { outcome: 'CAN' as const, causes: [], remediations: [] }
const channel: ResourceRef = { id: 'c1', name: 'general', type: 'CHANNEL', guildId: guildA }
const categoryA: ResourceRef = { id: 'ca', name: 'A', type: 'CATEGORY', guildId: guildA }
const categoryB: ResourceRef = { id: 'cb', name: 'B', type: 'CATEGORY', guildId: guildB }
const translationGroup: ResourceRef = { id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', name: 'Guides', type: 'TRANSLATION_GROUP', guildId: guildA }
const languageTarget: ResourceRef = { id: '11111111-1111-4111-8111-111111111111', name: 'French', type: 'LANGUAGE_TARGET', guildId: guildA, parentId: translationGroup.id }
const guildTarget: ResourceRef = { id: guildB, name: 'Beta', type: 'GUILD', guildId: guildB }
const context = (source = [channel], destination?: ResourceRef): ActionContext => ({
  source, ...(destination ? { destination } : {}),
  sourceUserCapabilities: { 'structure.read': { outcome: 'CAN', causes: [], remediations: [] }, 'structure.write': { outcome: 'CAN', causes: [], remediations: [] }, 'plans.create': { outcome: 'CAN', causes: [], remediations: [] }, 'permissions.read': { outcome: 'CAN', causes: [], remediations: [] } },
  sourceBotCapabilities: { REORDER_CHANNELS: { outcome: 'CAN', causes: [], remediations: [] }, CREATE_CHANNEL: { outcome: 'CAN', causes: [], remediations: [] } },
  destinationUserCapabilities: { 'plans.create': { outcome: 'CAN', causes: [], remediations: [] }, 'structure.write': { outcome: 'CAN', causes: [], remediations: [] } },
  destinationBotCapabilities: { CREATE_CHANNEL: { outcome: 'CAN', causes: [], remediations: [] } },
  destinationInstallationStatus: 'ACTIVE',
})

describe('STAGE 07 shared interaction model', () => {
  it('filters actions by cardinality, capability and tenant mode', () => {
    expect(resolveActions(context()).map((item) => item.action.id)).toContain('open')
    expect(resolveActions(context([channel, { ...channel, id: 'c2' }])).map((item) => item.action.id)).toContain('bulk')
    expect(resolveDropTarget(context([channel], categoryA)).actions.map((item) => item.action.id)).toContain('move')
    const cross = resolveDropTarget(context([channel], categoryB))
    expect(cross.crossGuild).toBe(true)
    expect(cross.actions.map((item) => item.action.id)).toContain('copy')
    const unknown = resolveDropTarget({ ...context([channel], categoryA), sourceBotCapabilities: {} })
    expect(unknown.actions.find((item) => item.action.id === 'move')).toMatchObject({ enabled: false, reasonKey: 'actions.disabled.unknown' })
  })

  it('preserves exact cross-Guild selection in the portable payload', () => {
    const intent = createActionIntent('copy', [channel], categoryB)
    expect(transferBody(intent)).toMatchObject({ source_guild_id: guildA, destination_guild_id: guildB, selection: { artifact_type: 'CHANNEL', channel_ids: ['c1'], category_ids: [] }, mode: 'COPY_AS_NEW' })
  })

  it('uses source read and independent destination write authority for cross-Guild copy', () => {
    const sourceReadOnly = context([channel], categoryB)
    sourceReadOnly.sourceUserCapabilities = { 'structure.read': { outcome: 'CAN', causes: [], remediations: [] }, 'plans.create': { outcome: 'CANNOT', causes: [], remediations: [] } }
    expect(resolveActions(sourceReadOnly).find((item) => item.action.id === 'copy')).toMatchObject({ enabled: true })

    const destinationReadOnly = context([channel], categoryB)
    destinationReadOnly.destinationUserCapabilities = { 'structure.read': { outcome: 'CAN', causes: [], remediations: [] }, 'plans.create': { outcome: 'CANNOT', causes: [], remediations: [] } }
    expect(resolveActions(destinationReadOnly).find((item) => item.action.id === 'copy')).toMatchObject({ enabled: false, reasonKey: 'actions.disabled.capability' })

    const botDenied = context([channel], categoryB)
    botDenied.destinationBotCapabilities = { CREATE_CHANNEL: { outcome: 'CANNOT', causes: [], remediations: [] } }
    expect(resolveActions(botDenied).find((item) => item.action.id === 'copy')).toMatchObject({ enabled: false })

    const botUnknown = context([channel], categoryB)
    botUnknown.destinationBotCapabilities = {}
    expect(resolveActions(botUnknown).find((item) => item.action.id === 'copy')).toMatchObject({ enabled: false, reasonKey: 'actions.disabled.unknown' })

    const inactive = context([channel], categoryB)
    inactive.destinationInstallationStatus = 'UNINSTALLED'
    expect(resolveActions(inactive).find((item) => item.action.id === 'copy')).toMatchObject({ enabled: false })
  })

  it('maps portable export exactly and gives every registry action a handler', () => {
    expect(exportBody(createActionIntent('export', [channel]))).toEqual({ selection: { artifact_type: 'CHANNEL', category_ids: [], channel_ids: ['c1'], role_ids: [] }, kind: 'LIBRARY' })
    expect(actions.every((action) => handledActionIds.has(action.id))).toBe(true)
  })

  it('treats backend 403 as final authority after an enabled preview', async () => {
    useSessionStore.getState().setMe({ authenticated: true, user: { discord_user_id: guildA, username: 'owner', global_name: null }, active_guild_id: guildA, csrf_token: 'csrf', policy_version: 1 })
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ error: { code: 'CAPABILITY_REQUIRED', message_key: 'errors.authorization.denied', params: {}, request_id: 'drift' } }, { status: 403 })))
    await expect(dispatchAction(createActionIntent('move', [channel], categoryA), guildA)).rejects.toMatchObject({ status: 403 })
  })

  it('resolves multilingual actions only for their real typed targets and group provider', () => {
    const languageContext = {
      ...context([translationGroup], languageTarget),
      providerCapabilities: { ROUTING_SUPPORTED: decisionCan },
    }
    expect(resolveActions(languageContext).filter((item) => item.enabled).map((item) => item.action.id)).toEqual(expect.arrayContaining(['CREATE_VARIANT', 'LINK_EXISTING_VARIANT', 'PREVIEW']))
    expect(resolveActions({ ...languageContext, destination: { ...languageTarget, parentId: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb' } })).toEqual([])
    const crossContext = context([translationGroup], guildTarget)
    expect(resolveActions(crossContext).find((item) => item.action.id === 'CLONE_UNLINKED')).toMatchObject({ enabled: true })
    crossContext.destinationUserCapabilities = { 'plans.create': { outcome: 'CANNOT', causes: [], remediations: [] }, 'structure.write': decisionCan }
    expect(resolveActions(crossContext).find((item) => item.action.id === 'CLONE_UNLINKED')).toMatchObject({ enabled: false })
  })

  it('dispatches multilingual registry actions to authoritative Stage08 endpoints', async () => {
    useSessionStore.getState().setMe({ authenticated: true, user: { discord_user_id: guildA, username: 'owner', global_name: null }, active_guild_id: guildA, csrf_token: 'csrf', policy_version: 1 })
    const requests: Array<{path:string; method:string; body:Record<string, unknown> | null}> = []
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const path = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, 'http://did.test').pathname
      requests.push({ path, method: init?.method ?? 'GET', body: typeof init?.body === 'string' ? JSON.parse(init.body) as Record<string, unknown> : null })
      if (path.endsWith('/variants/plan')) return Response.json({ plan_id: 'plan-variant' })
      if (path.endsWith('/link')) return Response.json({ id: 'linked-variant' })
      if (path.endsWith('/multilingual-clone/plan')) return Response.json({ destination_plan_id: 'plan-clone', transfer_status: 'COMPILED' })
      return Response.json({ id: translationGroup.id, routing_mode: 'HUB_AND_SPOKE', languages: [], category_variants: [], channel_variants: [] })
    }))

    await expect(dispatchAction(createActionIntent('CREATE_VARIANT', [translationGroup], languageTarget, { variantType: 'CHANNEL', desiredName: 'guides-fr', translationChannelGroupId: '33333333-3333-4333-8333-333333333333' }), guildA)).resolves.toMatchObject({ kind: 'PLAN', planId: 'plan-variant' })
    await expect(dispatchAction(createActionIntent('LINK_EXISTING_VARIANT', [translationGroup], languageTarget, { variantType: 'CHANNEL', discordResourceId: '100000000000000010', translationChannelGroupId: '33333333-3333-4333-8333-333333333333' }), guildA)).resolves.toMatchObject({ kind: 'LINK', variantId: 'linked-variant' })
    await expect(dispatchAction(createActionIntent('CLONE_UNLINKED', [translationGroup], guildTarget), guildA)).resolves.toMatchObject({ kind: 'TRANSFER', planId: 'plan-clone' })
    await expect(dispatchAction(createActionIntent('PREVIEW', [translationGroup]), guildA)).resolves.toMatchObject({ kind: 'PREVIEW' })

    expect(requests.map((item) => item.path)).toEqual([
      `/api/v1/guilds/${guildA}/translation-groups/${translationGroup.id}/variants/plan`,
      `/api/v1/guilds/${guildA}/translation-groups/${translationGroup.id}/link`,
      `/api/v1/guilds/${guildA}/multilingual-clone/plan`,
      `/api/v1/guilds/${guildA}/translation-groups/${translationGroup.id}`,
    ])
    expect(requests[0]?.body).toMatchObject({ language_profile_id: languageTarget.id, desired_name: 'guides-fr' })
    expect(requests[1]?.body).toMatchObject({ discord_resource_id: '100000000000000010', confirmed_explicit_selection: true })
    expect(requests[2]?.body).toMatchObject({ destination_guild_id: guildB, translation_group_id: translationGroup.id, mode: 'COPY_AS_NEW' })
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
    expect([0, 1, 2, 10].map(reconnectDelay)).toEqual([500, 1_000, 2_000, 30_000])
  })

  it('resolves a large action matrix within the dashboard interaction budget', () => {
    const started = performance.now()
    for (let index = 0; index < 20_000; index += 1) resolveActions(context([channel], index % 2 ? categoryA : categoryB))
    expect(performance.now() - started).toBeLessThan(500)
  })
})
