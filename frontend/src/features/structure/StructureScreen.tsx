import { useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useStructure } from '../../api/queries'
import type { Channel } from '../../api/types'
import type { DashboardContext } from '../../app/AppShell'
import { Badge, Button, Dialog, EmptyState, ErrorState, Input, Menu, MenuItem, Skeleton, Tree, TreeItem } from '../../shared/components/ui'
import { useInteractionStore } from '../../shared/state/interaction'
import { PointerGestureManager } from '../interaction/gestures'
import { actions, resolveActions, type ActionContext, type ResourceRef } from '../interaction/actions'
import { resolveDropTarget } from '../interaction/dropTarget'

const capabilities = new Set(['STRUCTURE_READ','STRUCTURE_WRITE','PLANS_CREATE','PERMISSIONS_READ'])
const botCapabilities = new Set(['MANAGE_CHANNEL'])
function ref(channel: Channel): ResourceRef { return { id: channel.id, name: channel.name, guildId: channel.guild_id, type: channel.type === 4 ? 'CATEGORY' : [10, 11, 12].includes(channel.type) ? 'THREAD' : 'CHANNEL' } }

export function StructureScreen() {
  const { t } = useTranslation(); const { me, guild, guilds } = useOutletContext<DashboardContext>(); const query = useStructure(me.user.discord_user_id, guild.guild_id)
  const [search, setSearch] = useState(''); const manager = useRef(new PointerGestureManager()); const navigate = useNavigate()
  const selection = useInteractionStore((state) => state.selection); const setSelection = useInteractionStore((state) => state.setSelection)
  const context = useInteractionStore((state) => state.context); const setContext = useInteractionStore((state) => state.setContext)
  const previewActionId = useInteractionStore((state) => state.previewActionId); const setPreview = useInteractionStore((state) => state.setPreview)
  const announce = useInteractionStore((state) => state.announce)
  const all = useMemo(() => query.data ? [...query.data.categories.flatMap((category) => [category, ...category.channels.flatMap((channel) => [channel, ...(channel.threads ?? [])])]), ...query.data.root_channels] : [], [query.data])
  const visible = (item: Channel) => item.name.toLocaleLowerCase().includes(search.toLocaleLowerCase())
  function actionContext(source = selection, destination?: ResourceRef): ActionContext { return destination ? { source, destination, userCapabilities: capabilities, botCapabilities } : { source, userCapabilities: capabilities, botCapabilities } }
  function openMenu(source: ResourceRef[], x: number, y: number, kind: 'object'|'drop', destination?: ResourceRef) { setSelection(source); setContext({ ...actionContext(source, destination), x, y, kind }) }
  function pointerDown(event: ReactPointerEvent, source: ResourceRef) { manager.current.start(event.nativeEvent, source); event.currentTarget.setPointerCapture(event.pointerId) }
  function pointerMove(event: ReactPointerEvent) { manager.current.move(event.nativeEvent) }
  function pointerUp(event: ReactPointerEvent) {
    const result = manager.current.finish(event.nativeEvent); event.currentTarget.releasePointerCapture(event.pointerId)
    if (!result || result.kind === 'cancel') return
    if (result.kind === 'context') { openMenu([result.source], result.x, result.y, 'object'); return }
    const element = document.elementFromPoint(result.x, result.y)?.closest<HTMLElement>('[data-drop-id]')
    const destinationId = element?.dataset.dropId; const destinationGuild = element?.dataset.dropGuild
    const destination = destinationId && destinationGuild ? { id: destinationId, name: element.dataset.dropName ?? destinationId, type: element.dataset.dropType as ResourceRef['type'], guildId: destinationGuild as ResourceRef['guildId'] } : undefined
    const resolution = resolveDropTarget(actionContext([result.source], destination))
    if (!resolution.valid) { announce(t('gesture.invalid')); return }
    if (result.kind === 'right-drag') openMenu([result.source], result.x, result.y, 'drop', destination)
    else { const action = resolution.actions.find((item) => item.enabled); if (action) { setPreview(action.action.id); announce(t(resolution.crossGuild ? 'gesture.copyPreview' : 'gesture.movePreview')) } }
  }
  function choose(actionId: string) { setContext(null); if (actionId === 'explain') navigate(`/guild/${guild.guild_id}/permissions`); else setPreview(actionId) }
  if (query.isLoading) return <Skeleton />
  if (query.isError) return <ErrorState retry={() => void query.refetch()} />
  return <section><div className="page-heading"><div><p className="eyebrow">{guild.name}</p><h1>{t('structure.title')}</h1></div><Input labelKey="common.search" value={search} onChange={(event) => setSearch(event.target.value)} /></div>{all.length === 0 && <EmptyState messageKey="structure.empty" />}<div className="structure-grid"><Tree>{query.data?.categories.filter(visible).map((category) => <ResourceItem key={category.id} item={category} selected={selection.some((item) => item.id === category.id)} onSelect={(value) => setSelection(value)} onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp}>{category.channels.filter(visible).map((channel) => <ResourceItem key={channel.id} item={channel} level={2} selected={selection.some((item) => item.id === channel.id)} onSelect={setSelection} onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp}>{channel.threads?.filter(visible).map((thread) => <ResourceItem key={thread.id} item={thread} level={3} selected={selection.some((item) => item.id === thread.id)} onSelect={setSelection} onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} />)}</ResourceItem>)}</ResourceItem>)}{query.data?.root_channels.filter(visible).map((channel) => <ResourceItem key={channel.id} item={channel} selected={selection.some((item) => item.id === channel.id)} onSelect={setSelection} onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} />)}</Tree><aside className="properties"><h2>{t('structure.properties')}</h2>{selection.map((item) => <div key={item.id}><strong>{item.name}</strong><Badge>{item.type}</Badge></div>)}<h2>{t('guilds.browser')}</h2>{guilds.filter((item) => item.guild_id !== guild.guild_id).map((item) => <button type="button" key={item.guild_id} className="drop-guild" data-drop-id={item.guild_id} data-drop-guild={item.guild_id} data-drop-name={item.name} data-drop-type="GUILD">{item.name}</button>)}</aside></div>{context && <Menu labelKey={context.kind === 'drop' ? 'context.dropTitle' : 'context.title'} style={{ left: context.x, top: context.y }}>{resolveActions(context).map(({action,enabled}) => <MenuItem key={action.id} disabled={!enabled} onSelect={() => choose(action.id)}>{t(action.labelKey)}</MenuItem>)}</Menu>}<Dialog open={previewActionId !== null} titleKey="dialog.previewTitle" onClose={() => setPreview(null)}><p>{t('dialog.noMutation')}</p><p>{previewActionId ? t(actions.find((action) => action.id === previewActionId)?.descriptionKey ?? 'actions.move.description') : null}</p><Button labelKey="common.preview" variant="primary" onClick={() => { if (previewActionId === 'copy' || previewActionId === 'clone') navigate(`/guild/${guild.guild_id}/clone`); else if (previewActionId === 'explain') navigate(`/guild/${guild.guild_id}/permissions`); setPreview(null) }} /></Dialog></section>
}

type ResourceItemProps = { item: Channel; level?: number; selected: boolean; children?: React.ReactNode; onSelect:(value:ResourceRef[])=>void; onPointerDown:(event:ReactPointerEvent,source:ResourceRef)=>void; onPointerMove:(event:ReactPointerEvent)=>void; onPointerUp:(event:ReactPointerEvent)=>void }
function ResourceItem({item,level=1,selected,children,onSelect,onPointerDown,onPointerMove,onPointerUp}:ResourceItemProps) {
  const source = ref(item)
  return <TreeItem level={level} selected={selected} data-drop-id={item.id} data-drop-guild={item.guild_id} data-drop-name={item.name} data-drop-type={source.type} onClick={(event) => { const current = useInteractionStore.getState().selection; onSelect(event.ctrlKey || event.metaKey ? (selected ? current.filter((item) => item.id !== source.id) : [...current, source]) : [source]) }} onContextMenu={(event) => event.preventDefault()} onPointerDown={(event) => onPointerDown(event,source)} onPointerMove={onPointerMove} onPointerUp={onPointerUp}><span className="resource-name">{item.type === 4 ? '◇' : '#'} {item.name}</span>{item.freshness !== 'FRESH' && <Badge tone="warning">{item.freshness}</Badge>}{children && <div role="group">{children}</div>}</TreeItem>
}
