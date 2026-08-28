import { Children, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ApiError } from '../../api/client'
import { useDashboardCapabilities, useStructure } from '../../api/queries'
import type { Channel, DashboardCapabilities } from '../../api/types'
import type { DashboardContext } from '../../app/AppShell'
import { Badge, Button, Dialog, EmptyState, ErrorState, Input, Menu, MenuItem, Skeleton, Tree, TreeItem } from '../../shared/components/ui'
import { useInteractionStore } from '../../shared/state/interaction'
import { actions, resolveActions, type ActionContext, type ResourceRef } from '../interaction/actions'
import { createActionIntent, dispatchAction } from '../interaction/dispatcher'
import { resolveDropTarget } from '../interaction/dropTarget'
import { PointerGestureManager } from '../interaction/gestures'

function ref(channel: Channel): ResourceRef {
  return { id: channel.id, name: channel.name, guildId: channel.guild_id, type: channel.type === 4 ? 'CATEGORY' : [10, 11, 12].includes(channel.type) ? 'THREAD' : 'CHANNEL', position: channel.position, parentId: channel.parent_id, channelType: channel.type }
}
const emptyCapabilities: DashboardCapabilities = { guild_id: '' as DashboardCapabilities['guild_id'], source: 'AUTHORIZATION_AND_LOCAL_CACHE', discord_rest_calls: 0, user_capabilities: {}, scoped_capabilities: { scope_kind: 'GUILD', scope_id: '*', capabilities: {} }, bot_operations: {}, coverage: 'UNKNOWN', completeness: 'UNKNOWN', freshness: 'UNKNOWN' }

export function StructureScreen() {
  const { t } = useTranslation(); const { me, guild, guilds, capabilities: globalCapabilities } = useOutletContext<DashboardContext>()
  const query = useStructure(me.user.discord_user_id, guild.guild_id); const [search, setSearch] = useState(''); const [problemKey, setProblemKey] = useState<'errors.authorization.denied'|'errors.generic'|null>(null)
  const manager = useRef(new PointerGestureManager()); const navigate = useNavigate(); const client = useQueryClient()
  const selection = useInteractionStore((state) => state.selection); const setSelection = useInteractionStore((state) => state.setSelection)
  const context = useInteractionStore((state) => state.context); const setContext = useInteractionStore((state) => state.setContext)
  const previewIntent = useInteractionStore((state) => state.previewIntent); const setPreview = useInteractionStore((state) => state.setPreview); const announce = useInteractionStore((state) => state.announce)
  const scoped = useDashboardCapabilities(me.user.discord_user_id, guild.guild_id, selection.length === 1 ? selection[0]?.id : undefined)
  const capabilities = scoped.data ?? globalCapabilities ?? emptyCapabilities
  const all = useMemo(() => query.data ? [...query.data.categories.flatMap((category) => [category, ...category.channels.flatMap((channel) => [channel, ...(channel.threads ?? [])])]), ...query.data.root_channels] : [], [query.data])
  const visible = (item: Channel) => item.name.toLocaleLowerCase().includes(search.toLocaleLowerCase())

  useEffect(() => { const cancel = (event: KeyboardEvent) => { if (event.key === 'Escape' && manager.current.cancel()) { announce(t('gesture.cancelled')); setContext(null) } }; document.addEventListener('keydown', cancel); return () => document.removeEventListener('keydown', cancel) }, [announce, setContext, t])
  function actionContext(source = selection, destination?: ResourceRef): ActionContext { return { source, ...(destination ? { destination } : {}), userCapabilities: capabilities.user_capabilities, botCapabilities: capabilities.bot_operations } }
  function openMenu(source: ResourceRef[], x: number, y: number, kind: 'object'|'drop', destination?: ResourceRef) { setSelection(source); setContext({ ...actionContext(source, destination), x, y, kind }) }
  function pointerDown(event: ReactPointerEvent, source: ResourceRef) { manager.current.start(event.nativeEvent, source); event.currentTarget.setPointerCapture(event.pointerId); announce(t('a11y.dragStarted', { name: source.name })) }
  function pointerMove(event: ReactPointerEvent) { manager.current.move(event.nativeEvent) }
  function cancelGesture() { if (manager.current.cancel()) announce(t('gesture.cancelled')) }
  function pointerUp(event: ReactPointerEvent) {
    const result = manager.current.finish(event.nativeEvent); if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
    if (!result || result.kind === 'cancel') return
    if (result.kind === 'context') { openMenu([result.source], result.x, result.y, 'object'); return }
    const element = document.elementFromPoint(result.x, result.y)?.closest<HTMLElement>('[data-drop-id]'); const destinationId = element?.dataset.dropId; const destinationGuild = element?.dataset.dropGuild
    const destination = destinationId && destinationGuild ? { id: destinationId, name: element.dataset.dropName ?? destinationId, type: element.dataset.dropType as ResourceRef['type'], guildId: destinationGuild as ResourceRef['guildId'] } : undefined
    const resolution = resolveDropTarget(actionContext([result.source], destination)); if (!resolution.valid) { announce(t('gesture.invalid')); return }
    if (result.kind === 'right-drag') openMenu([result.source], result.x, result.y, 'drop', destination)
    else { const action = resolution.actions.find((item) => item.enabled); if (action) { setPreview(createActionIntent(action.action.id, [result.source], destination)); announce(t(resolution.crossGuild ? 'gesture.copyPreview' : 'gesture.movePreview')) } }
  }
  function choose(actionId: string) { if (!context) return; const intent = createActionIntent(actionId, context.source, context.destination); setContext(null); if (actionId === 'open' || actionId === 'explain') void execute(intent); else setPreview(intent) }
  async function execute(intent = previewIntent) { if (!intent) return; setProblemKey(null); try { const result = await dispatchAction(intent, guild.guild_id, 'PREVIEW'); if (!(result.kind === 'ROUTE' && result.path.endsWith('/clone'))) setPreview(null); await client.invalidateQueries({ queryKey: ['did', me.user.discord_user_id, guild.guild_id] }); navigate(result.path) } catch (error) { setProblemKey(error instanceof ApiError && error.status === 403 ? 'errors.authorization.denied' : 'errors.generic'); await client.invalidateQueries({ queryKey: ['did', me.user.discord_user_id, guild.guild_id, 'dashboard-capabilities'] }) } }
  if (query.isLoading) return <Skeleton />
  if (query.isError) return <ErrorState retry={() => void query.refetch()} />
  return <section><div className="page-heading"><div><p className="eyebrow">{guild.name}</p><h1>{t('structure.title')}</h1></div><Input labelKey="common.search" value={search} onChange={(event) => setSearch(event.target.value)} /></div>{all.length === 0 && <EmptyState messageKey="structure.empty" />}<div className="structure-grid"><Tree>{query.data?.categories.filter(visible).map((category) => <ResourceItem key={category.id} item={category} selected={selection.some((item) => item.id === category.id)} onSelect={setSelection} onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={cancelGesture}>{category.channels.filter(visible).map((channel) => <ResourceItem key={channel.id} item={channel} level={2} selected={selection.some((item) => item.id === channel.id)} onSelect={setSelection} onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={cancelGesture}>{channel.threads?.filter(visible).map((thread) => <ResourceItem key={thread.id} item={thread} level={3} selected={selection.some((item) => item.id === thread.id)} onSelect={setSelection} onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={cancelGesture} />)}</ResourceItem>)}</ResourceItem>)}{query.data?.root_channels.filter(visible).map((channel) => <ResourceItem key={channel.id} item={channel} selected={selection.some((item) => item.id === channel.id)} onSelect={setSelection} onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={cancelGesture} />)}</Tree><aside className="properties"><h2>{t('structure.properties')}</h2>{selection.map((item) => <div key={item.id}><strong>{item.name}</strong><Badge>{t(`resource.${item.type.toLowerCase()}` as 'resource.channel')}</Badge></div>)}<h2>{t('guilds.browser')}</h2>{guilds.filter((item) => item.guild_id !== guild.guild_id).map((item) => <button type="button" key={item.guild_id} className="drop-guild" data-drop-id={item.guild_id} data-drop-guild={item.guild_id} data-drop-name={item.name} data-drop-type="GUILD">{item.name}</button>)}</aside></div>{context && <Menu labelKey={context.kind === 'drop' ? 'context.dropTitle' : 'context.title'} style={{ left: context.x, top: context.y }} onClose={() => setContext(null)}>{resolveActions(context).map(({action,enabled,reasonKey}) => <MenuItem key={action.id} disabled={!enabled} disabledReasonKey={reasonKey} onSelect={() => choose(action.id)}>{t(action.labelKey)}</MenuItem>)}</Menu>}<Dialog open={previewIntent !== null} titleKey="dialog.previewTitle" onClose={() => { setPreview(null); setProblemKey(null) }}><p>{t('dialog.noMutation')}</p><p>{previewIntent ? t(actions.find((action) => action.id === previewIntent.actionId)?.descriptionKey ?? 'actions.move.description') : null}</p>{problemKey && <p role="alert">{t(problemKey, { requestId: 'unknown' })}</p>}<Button labelKey="common.preview" variant="primary" onClick={() => void execute()} /></Dialog></section>
}

type ResourceItemProps = { item: Channel; level?: number; selected: boolean; children?: React.ReactNode; onSelect:(value:ResourceRef[])=>void; onPointerDown:(event:ReactPointerEvent,source:ResourceRef)=>void; onPointerMove:(event:ReactPointerEvent)=>void; onPointerUp:(event:ReactPointerEvent)=>void; onPointerCancel:()=>void }
function ResourceItem({item,level=1,selected,children,onSelect,onPointerDown,onPointerMove,onPointerUp,onPointerCancel}:ResourceItemProps) {
  const { t } = useTranslation(); const source = ref(item)
  return <TreeItem level={level} selected={selected} expandable={Children.count(children) > 0} data-drop-id={item.id} data-drop-guild={item.guild_id} data-drop-name={item.name} data-drop-type={source.type}
    onClick={(event) => { event.stopPropagation(); const current = useInteractionStore.getState().selection; onSelect(event.ctrlKey || event.metaKey ? (selected ? current.filter((entry) => entry.id !== source.id) : [...current, source]) : [source]) }}
    onContextMenu={(event) => { event.preventDefault(); event.stopPropagation() }}
    onPointerDown={(event) => { event.stopPropagation(); onPointerDown(event,source) }}
    onPointerMove={(event) => { event.stopPropagation(); onPointerMove(event) }}
    onPointerUp={(event) => { event.stopPropagation(); onPointerUp(event) }}
    onPointerCancel={(event) => { event.stopPropagation(); onPointerCancel() }}
    onLostPointerCapture={(event) => { event.stopPropagation(); onPointerCancel() }}>
    <span className="resource-name" aria-label={t(source.type === 'CATEGORY' ? 'structure.category' : source.type === 'THREAD' ? 'structure.thread' : 'structure.channel')}>{item.type === 4 ? '◇' : '#'} {item.name}</span>
    {item.freshness !== 'FRESH' && <Badge tone="warning">{t('common.stale')}</Badge>}{children && <div role="group">{children}</div>}
  </TreeItem>
}
