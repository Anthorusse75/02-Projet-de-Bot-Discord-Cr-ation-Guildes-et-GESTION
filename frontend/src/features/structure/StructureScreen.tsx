import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ApiError } from '../../api/client'
import { useDashboardCapabilities, useGuildDashboardCapabilities, useStructure } from '../../api/queries'
import { queryKeys } from '../../api/queryKeys'
import type { Channel, DashboardCapabilities, Guild } from '../../api/types'
import type { DiscordSnowflake } from '../../shared/discord-id'
import type { DashboardContext } from '../../app/AppShell'
import { Badge, Button, Dialog, EmptyState, ErrorState, Input, Menu, MenuItem, Select, Skeleton, Toast, Tree, TreeItem } from '../../shared/components/ui'
import { useInteractionStore } from '../../shared/state/interaction'
import { actions, resolveActions, type ActionContext, type ResourceRef } from '../interaction/actions'
import { createActionIntent, dispatchAction } from '../interaction/dispatcher'
import { resolveDropTarget } from '../interaction/dropTarget'
import { PointerGestureManager } from '../interaction/gestures'
import { LogicalGroupsPanel } from './LogicalGroupsPanel'
import { NameEditor } from './NameEditor'
import { validateDiscordResourceName } from './naming'

function resourceRef(channel: Channel): ResourceRef {
  return {
    id: channel.id,
    name: channel.name,
    guildId: channel.guild_id,
    type: channel.type === 4 ? 'CATEGORY' : [10, 11, 12].includes(channel.type) ? 'THREAD' : 'CHANNEL',
    position: channel.position,
    parentId: channel.parent_id,
    channelType: channel.type,
  }
}

const emptyCapabilities: DashboardCapabilities = {
  guild_id: '' as DashboardCapabilities['guild_id'],
  source: 'AUTHORIZATION_AND_LOCAL_CACHE',
  discord_rest_calls: 0,
  user_capabilities: {},
  scoped_capabilities: { scope_kind: 'GUILD', scope_id: '*', capabilities: {} },
  bot_operations: {},
  coverage: 'UNKNOWN',
  completeness: 'UNKNOWN',
  freshness: 'UNKNOWN',
}

type DragVisual = { source: ResourceRef; x: number; y: number; rightButton: boolean }
type RenameDraft = { source: ResourceRef; originalName: string; value: string; busy: boolean }
type DropDataset = HTMLElement & { dataset: DOMStringMap & { dropId?: string; dropGuild?: string; dropName?: string; dropType?: string; dropPosition?: string; dropParent?: string } }

function dropKey(destination: ResourceRef | undefined): string | null {
  return destination ? `${destination.guildId}:${destination.id}` : null
}

function destinationAt(x: number, y: number): ResourceRef | undefined {
  const element = document.elementFromPoint(x, y)?.closest<DropDataset>('[data-drop-id]')
  const id = element?.dataset.dropId
  const guildId = element?.dataset.dropGuild
  const type = element?.dataset.dropType as ResourceRef['type'] | undefined
  if (!element || !id || !guildId || !type) return undefined
  const destination: ResourceRef = { id, guildId: guildId as ResourceRef['guildId'], type, name: element.dataset.dropName ?? id }
  if (element.dataset.dropPosition !== undefined) {
    const value = Number(element.dataset.dropPosition)
    if (Number.isFinite(value)) destination.position = value
  }
  if (element.dataset.dropParent !== undefined) destination.parentId = element.dataset.dropParent || null
  return destination
}

function flattenStructure(categories: Array<Channel & { channels: Channel[] }>, roots: Channel[]): Channel[] {
  return [
    ...categories.flatMap((category) => [category, ...category.channels.flatMap((channel) => [channel, ...(channel.threads ?? [])])]),
    ...roots.flatMap((channel) => [channel, ...(channel.threads ?? [])]),
  ]
}

function countStructure(categories: Array<Channel & { channels: Channel[] }>, roots: Channel[]) {
  const channels = [...categories.flatMap((category) => category.channels), ...roots]
  return {
    categories: categories.length,
    channels: channels.length,
    threads: channels.reduce((total, channel) => total + (channel.threads?.length ?? 0), 0),
  }
}

export function StructureScreen() {
  const { t } = useTranslation()
  const { me, guild, guilds, capabilities: globalCapabilities } = useOutletContext<DashboardContext>()
  const [includeHiddenDeleted, setIncludeHiddenDeleted] = useState(false)
  const [search, setSearch] = useState('')
  const [problemKey, setProblemKey] = useState<'errors.authorization.denied'|'errors.generic'|null>(null)
  const [feedbackKey, setFeedbackKey] = useState<'actions.export.saved'|null>(null)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const expansionInitialized = useRef(false)
  const manager = useRef(new PointerGestureManager())
  const gestureSource = useRef<{ source: ResourceRef; rightButton: boolean } | null>(null)
  const lastLabelClick = useRef<{ resourceId: string; at: number } | null>(null)
  const [dragVisual, setDragVisual] = useState<DragVisual | null>(null)
  const [dragHoverKey, setDragHoverKey] = useState<string | null>(null)
  const [renameDraft, setRenameDraft] = useState<RenameDraft | null>(null)
  const navigate = useNavigate()
  const client = useQueryClient()
  const query = useStructure(me.user.discord_user_id, guild.guild_id, includeHiddenDeleted)
  const selection = useInteractionStore((state) => state.selection)
  const setSelection = useInteractionStore((state) => state.setSelection)
  const context = useInteractionStore((state) => state.context)
  const setContext = useInteractionStore((state) => state.setContext)
  const previewIntent = useInteractionStore((state) => state.previewIntent)
  const setPreview = useInteractionStore((state) => state.setPreview)
  const announce = useInteractionStore((state) => state.announce)
  const scoped = useDashboardCapabilities(me.user.discord_user_id, guild.guild_id, selection.length === 1 ? selection[0]?.id : undefined)
  const capabilities = scoped.data ?? globalCapabilities ?? emptyCapabilities
  const destinationGuilds = guilds.filter((item) => item.guild_id !== guild.guild_id && item.installation_status === 'ACTIVE')
  const destinationQueries = useGuildDashboardCapabilities(me.user.discord_user_id, destinationGuilds.map((item) => item.guild_id))
  const destinationCapabilities = new Map(destinationGuilds.map((item, index) => [item.guild_id, destinationQueries[index]?.data]))

  const all = useMemo(() => query.data ? flattenStructure(query.data.categories, query.data.root_channels) : [], [query.data])
  const byId = useMemo(() => new Map<string, Channel>(all.map((item) => [String(item.id), item])), [all])
  const counts = useMemo(() => query.data ? countStructure(query.data.categories, query.data.root_channels) : { categories: 0, channels: 0, threads: 0 }, [query.data])
  const normalizedSearch = search.trim().toLocaleLowerCase()
  const matches = (item: Channel) => !normalizedSearch || item.name.toLocaleLowerCase().includes(normalizedSearch)
  const categoryMatches = (category: Channel & { channels: Channel[] }) => matches(category) || category.channels.some((channel) => matches(channel) || channel.threads?.some(matches))
  const rootMatches = (channel: Channel) => matches(channel) || Boolean(channel.threads?.some(matches))

  useEffect(() => {
    if (!query.data || expansionInitialized.current) return
    expansionInitialized.current = true
    setExpanded(new Set<string>(query.data.categories.map((category) => String(category.id))))
  }, [query.data])

  useEffect(() => {
    if (!query.data || selection.length === 0) return
    const existing = new Set<string>(all.map((item) => String(item.id)))
    const next = selection.filter((item) => existing.has(item.id))
    if (next.length !== selection.length) setSelection(next)
  }, [all, query.data, selection, setSelection])

  useEffect(() => {
    const cancel = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      if (manager.current.cancel()) {
        setDragVisual(null)
        setDragHoverKey(null)
        gestureSource.current = null
        announce(t('gesture.cancelled'))
        setContext(null)
      }
    }
    document.addEventListener('keydown', cancel)
    return () => document.removeEventListener('keydown', cancel)
  }, [announce, setContext, t])

  function actionContext(source = selection, destination?: ResourceRef): ActionContext {
    const destinationGuild = destination ? guilds.find((item) => item.guild_id === destination.guildId) : undefined
    const destinationCapability = destination?.guildId === guild.guild_id ? capabilities : destination ? destinationCapabilities.get(destination.guildId) : undefined
    return {
      source,
      ...(destination ? { destination } : {}),
      sourceUserCapabilities: capabilities.user_capabilities,
      sourceBotCapabilities: capabilities.bot_operations,
      ...(destinationCapability ? { destinationUserCapabilities: destinationCapability.user_capabilities, destinationBotCapabilities: destinationCapability.bot_operations } : {}),
      ...(destinationGuild ? { destinationInstallationStatus: destinationGuild.installation_status } : {}),
    }
  }

  function openMenu(source: ResourceRef[], x: number, y: number, kind: 'object'|'drop', destination?: ResourceRef) {
    setSelection(source)
    setContext({ ...actionContext(source, destination), x, y, kind })
  }

  function pointerDown(event: ReactPointerEvent, source: ResourceRef) {
    manager.current.start(event.nativeEvent, source)
    gestureSource.current = { source, rightButton: event.button === 2 }
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  function pointerMove(event: ReactPointerEvent) {
    if (!manager.current.move(event.nativeEvent) || !gestureSource.current) return
    const visual = gestureSource.current
    setDragVisual({ source: visual.source, x: event.clientX, y: event.clientY, rightButton: visual.rightButton })
    const destination = destinationAt(event.clientX, event.clientY)
    const resolution = resolveDropTarget(actionContext([visual.source], destination))
    setDragHoverKey(resolution.valid ? dropKey(destination) : null)
  }

  function clearGestureVisual() {
    setDragVisual(null)
    setDragHoverKey(null)
    gestureSource.current = null
  }

  function cancelGesture() {
    if (manager.current.cancel()) announce(t('gesture.cancelled'))
    clearGestureVisual()
  }

  function pointerUp(event: ReactPointerEvent) {
    const result = manager.current.finish(event.nativeEvent)
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
    clearGestureVisual()
    if (!result || result.kind === 'cancel') return
    if (result.kind === 'context') {
      const chosen = selection.some((item) => item.id === result.source.id) ? selection : [result.source]
      openMenu(chosen, result.x, result.y, 'object')
      return
    }
    const destination = destinationAt(result.x, result.y)
    const resolution = resolveDropTarget(actionContext([result.source], destination))
    if (!resolution.valid) { announce(t('gesture.invalid')); return }
    if (result.kind === 'right-drag') { openMenu([result.source], result.x, result.y, 'drop', destination); return }
    const action = resolution.actions.find((item) => item.enabled)
    if (action) {
      setPreview(createActionIntent(action.action.id, [result.source], destination))
      announce(t(resolution.crossGuild ? 'gesture.copyPreview' : 'gesture.movePreview'))
    }
  }

  function choose(actionId: string) {
    if (!context) return
    if (actionId === 'rename') {
      const source = context.source[0]
      setContext(null)
      if (source) beginRename(source)
      return
    }
    const intent = createActionIntent(actionId, context.source, context.destination)
    setContext(null)
    if (actionId === 'open' || actionId === 'explain') void execute(intent)
    else setPreview(intent)
  }

  function beginRename(source: ResourceRef) {
    const availability = resolveActions(actionContext([source])).find((item) => item.action.id === 'rename')
    if (!availability?.enabled) { setProblemKey('errors.authorization.denied'); return }
    setSelection([source])
    setProblemKey(null)
    setRenameDraft({ source, originalName: source.name, value: source.name, busy: false })
  }

  function selectFromLabel(source: ResourceRef, event: ReactMouseEvent) {
    event.stopPropagation()
    const current = useInteractionStore.getState().selection
    const selected = current.some((item) => item.id === source.id)
    const now = performance.now()
    const previous = lastLabelClick.current
    const elapsed = previous?.resourceId === source.id ? now - previous.at : null

    if (!selected || event.ctrlKey || event.metaKey) {
      setSelection(event.ctrlKey || event.metaKey
        ? selected ? current.filter((item) => item.id !== source.id) : [...current, source]
        : [source])
    } else if (elapsed !== null && elapsed >= 350 && elapsed <= 1_400 && source.type !== 'THREAD') {
      beginRename(source)
    }
    lastLabelClick.current = { resourceId: source.id, at: now }
  }

  async function submitRename() {
    if (!renameDraft || !validateDiscordResourceName(renameDraft.value).valid || renameDraft.value === renameDraft.originalName) return
    const source = { ...renameDraft.source, name: renameDraft.value }
    const intent = createActionIntent('rename', [source])
    setRenameDraft((current) => current ? { ...current, busy: true } : null)
    try {
      const result = await dispatchAction(intent, guild.guild_id, 'PREVIEW')
      setRenameDraft(null)
      await client.invalidateQueries({ queryKey: ['did', me.user.discord_user_id, guild.guild_id] })
      navigate(result.path)
    } catch (error) {
      setRenameDraft((current) => current ? { ...current, busy: false } : null)
      setProblemKey(error instanceof ApiError && error.status === 403 ? 'errors.authorization.denied' : 'errors.generic')
    }
  }

  async function execute(intent = previewIntent) {
    if (!intent) return
    const availability = resolveActions(actionContext(intent.source, intent.destination)).find((item) => item.action.id === intent.actionId)
    if (!availability?.enabled) { setProblemKey('errors.authorization.denied'); return }
    setProblemKey(null)
    setFeedbackKey(null)
    try {
      const result = await dispatchAction(intent, guild.guild_id, 'PREVIEW')
      if (!(result.kind === 'ROUTE' && result.path.endsWith('/clone'))) setPreview(null)
      await client.invalidateQueries({ queryKey: ['did', me.user.discord_user_id, guild.guild_id] })
      if (result.kind === 'EXPORT') {
        await client.invalidateQueries({ queryKey: queryKeys.library(me.user.discord_user_id) })
        setFeedbackKey('actions.export.saved')
        announce(t('actions.export.saved'))
        return
      }
      navigate(result.path)
    } catch (error) {
      setProblemKey(error instanceof ApiError && error.status === 403 ? 'errors.authorization.denied' : 'errors.generic')
      await client.invalidateQueries({ queryKey: ['did', me.user.discord_user_id, guild.guild_id, 'dashboard-capabilities'] })
      const destinationGuildId = intent.destination?.guildId
      if (destinationGuildId && destinationGuildId !== guild.guild_id) await client.invalidateQueries({ queryKey: ['did', me.user.discord_user_id, destinationGuildId, 'dashboard-capabilities'] })
    }
  }

  function openSelectionActions(anchor: HTMLElement) {
    if (selection.length === 0) return
    const rect = anchor.getBoundingClientRect()
    openMenu(selection, Math.min(rect.left, window.innerWidth - 260), rect.bottom + 8, 'object')
  }

  const previewAction = previewIntent ? actions.find((action) => action.id === previewIntent.actionId) : undefined
  const localRoot: ResourceRef = { id: guild.guild_id, name: guild.name, type: 'GUILD', guildId: guild.guild_id }
  const targetCandidates: ResourceRef[] = previewIntent && previewAction?.requiresTarget ? [
    ...(previewAction.guildMode !== 'CROSS' ? [localRoot] : []),
    ...(previewAction.guildMode !== 'CROSS' ? (query.data?.categories ?? []).map(resourceRef) : []),
    ...(previewAction.id === 'move' && previewIntent.source[0]?.type === 'CHANNEL'
      ? all.filter((item) => item.type !== 4 && ![10,11,12].includes(item.type) && item.id !== previewIntent.source[0]?.id).map(resourceRef)
      : []),
    ...(previewAction.guildMode !== 'SAME' ? destinationGuilds.map((item) => ({ id: item.guild_id, name: item.name, type: 'GUILD' as const, guildId: item.guild_id })) : []),
  ] : []
  const previewAvailability = previewIntent ? resolveActions(actionContext(previewIntent.source, previewIntent.destination)).find((item) => item.action.id === previewIntent.actionId) : undefined
  const selectedItem = selection.length === 1 ? byId.get(selection[0]?.id ?? '') : undefined

  if (query.isLoading) return <Skeleton />
  if (query.isError) return <ErrorState retry={() => void query.refetch()} />

  const categories = query.data?.categories ?? []
  const roots = query.data?.root_channels ?? []
  const filteredCategories = categories.filter(categoryMatches)
  const filteredRoots = roots.filter(rootMatches)
  const hasFilteredResults = filteredCategories.length > 0 || filteredRoots.length > 0

  return (
    <section className="structure-explorer-screen">
      <header className="structure-explorer-heading">
        <div><p className="eyebrow">{t('structure.explorerEyebrow')}</p><h1>{t('structure.title')}</h1><p className="structure-explorer-subtitle">{t('structure.explorerSubtitle')}</p></div>
        <div className="structure-summary" aria-label={t('structure.title')}><span>{t('structure.summary.categories', { count: counts.categories })}</span><span>{t('structure.summary.channels', { count: counts.channels })}</span><span>{t('structure.summary.threads', { count: counts.threads })}</span></div>
      </header>

      <div className="structure-toolbar">
        <div className="structure-search"><Input labelKey="common.search" value={search} onChange={(event) => setSearch(event.target.value)} /></div>
        <label className="structure-hidden-toggle"><input type="checkbox" checked={includeHiddenDeleted} onChange={(event) => setIncludeHiddenDeleted(event.target.checked)} /><span>{t('structure.showHiddenShort')}</span></label>
        <button type="button" className="structure-action-button" disabled={selection.length === 0} onClick={(event) => openSelectionActions(event.currentTarget)}><span aria-hidden="true">•••</span>{t('structure.selection.actions')}{selection.length > 0 && <strong>{selection.length}</strong>}</button>
      </div>

      {feedbackKey && <Toast>{t(feedbackKey)}</Toast>}
      {all.length === 0 && <EmptyState messageKey="structure.empty" />}

      {all.length > 0 && (
        <div className="structure-workbench">
          <section className="structure-tree-panel" aria-label={t('a11y.tree')}>
            <div className="structure-panel-title"><div><span className="structure-panel-icon" aria-hidden="true">⌘</span><div><strong>{guild.name}</strong><small>{t('structure.current')}</small></div></div><Badge tone={capabilities.freshness === 'FRESH' ? 'ok' : 'warning'}>{capabilities.freshness === 'FRESH' ? t('structure.current') : t('structure.stale')}</Badge></div>
            <LogicalGroupsPanel guildId={guild.guild_id} userId={me.user.discord_user_id} canWrite={(capabilities.user_capabilities['structure.write']?.outcome ?? 'UNKNOWN') === 'CAN'} />
            {!hasFilteredResults && <div className="structure-no-match">{t('structure.noMatch')}</div>}
            {hasFilteredResults && (
              <Tree>
                {filteredCategories.map((category) => (
                  <ResourceItem key={category.id} item={category} selected={selection.some((item) => item.id === category.id)} expanded={expanded.has(String(category.id))} dropHoverKey={dragHoverKey} renameDraft={renameDraft}
                    onToggle={() => toggleExpanded(setExpanded, String(category.id))} onSelect={setSelection} onLabelClick={selectFromLabel} onMenu={openMenu} onRename={beginRename} onRenameChange={(value) => setRenameDraft((current) => current ? { ...current, value } : null)} onRenameSubmit={() => void submitRename()} onRenameCancel={() => setRenameDraft(null)} onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={cancelGesture}>
                    {category.channels.filter((channel) => matches(channel) || channel.threads?.some(matches)).map((channel) => (
                      <ResourceItem key={channel.id} item={channel} level={2} selected={selection.some((item) => item.id === channel.id)} expanded={expanded.has(String(channel.id))} dropHoverKey={dragHoverKey} renameDraft={renameDraft}
                        onToggle={() => toggleExpanded(setExpanded, String(channel.id))} onSelect={setSelection} onLabelClick={selectFromLabel} onMenu={openMenu} onRename={beginRename} onRenameChange={(value) => setRenameDraft((current) => current ? { ...current, value } : null)} onRenameSubmit={() => void submitRename()} onRenameCancel={() => setRenameDraft(null)} onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={cancelGesture}>
                        {channel.threads?.filter(matches).map((thread) => <ResourceItem key={thread.id} item={thread} level={3} selected={selection.some((item) => item.id === thread.id)} expanded={false} dropHoverKey={dragHoverKey} renameDraft={renameDraft} onToggle={() => undefined} onSelect={setSelection} onLabelClick={selectFromLabel} onMenu={openMenu} onRename={beginRename} onRenameChange={(value) => setRenameDraft((current) => current ? { ...current, value } : null)} onRenameSubmit={() => void submitRename()} onRenameCancel={() => setRenameDraft(null)} onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={cancelGesture} />)}
                      </ResourceItem>
                    ))}
                  </ResourceItem>
                ))}
                {filteredRoots.length > 0 && <div className="structure-root-group"><div className="structure-root-heading"><span aria-hidden="true">⌂</span><span>{t('structure.rootLabel')}</span></div>{filteredRoots.map((channel) => (
                  <ResourceItem key={channel.id} item={channel} selected={selection.some((item) => item.id === channel.id)} expanded={expanded.has(String(channel.id))} dropHoverKey={dragHoverKey} renameDraft={renameDraft}
                    onToggle={() => toggleExpanded(setExpanded, String(channel.id))} onSelect={setSelection} onLabelClick={selectFromLabel} onMenu={openMenu} onRename={beginRename} onRenameChange={(value) => setRenameDraft((current) => current ? { ...current, value } : null)} onRenameSubmit={() => void submitRename()} onRenameCancel={() => setRenameDraft(null)} onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={cancelGesture}>
                    {channel.threads?.filter(matches).map((thread) => <ResourceItem key={thread.id} item={thread} level={2} selected={selection.some((item) => item.id === thread.id)} expanded={false} dropHoverKey={dragHoverKey} renameDraft={renameDraft} onToggle={() => undefined} onSelect={setSelection} onLabelClick={selectFromLabel} onMenu={openMenu} onRename={beginRename} onRenameChange={(value) => setRenameDraft((current) => current ? { ...current, value } : null)} onRenameSubmit={() => void submitRename()} onRenameCancel={() => setRenameDraft(null)} onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={cancelGesture} />)}
                  </ResourceItem>
                ))}</div>}
              </Tree>
            )}
          </section>

          <aside className="structure-inspector-panel"><Inspector selection={selection} item={selectedItem} capabilities={capabilities} onActions={openSelectionActions} /></aside>

          <aside className="structure-destinations-panel">
            <div className="structure-destination-heading"><p className="eyebrow">{t('structure.destinations.title')}</p><p>{t('structure.destinations.subtitle')}</p></div>
            <div className="destination-section-label">{t('structure.destinations.thisServer')}</div>
            <DropTargetCard destination={localRoot} hoverKey={dragHoverKey} title={t('structure.rootLabel')} subtitle={t('structure.drop.root')} icon="⌂" />
            <div className="destination-section-label">{t('structure.destinations.otherServers')}</div>
            <div className="destination-guild-list">{destinationGuilds.map((item) => <DestinationGuildCard key={item.guild_id} guild={item} userId={me.user.discord_user_id} hoverKey={dragHoverKey} />)}</div>
          </aside>
        </div>
      )}

      {dragVisual && <div className="structure-drag-overlay" style={{ transform: `translate3d(${dragVisual.x + 14}px, ${dragVisual.y + 14}px, 0)` }}><span className="resource-kind-icon" aria-hidden="true">{dragVisual.source.type === 'CATEGORY' ? '▰' : '#'}</span><div><strong>{dragVisual.source.name}</strong><small>{t(dragVisual.rightButton ? 'structure.drag.rightRelease' : dragHoverKey?.startsWith(`${guild.guild_id}:`) ? 'structure.drag.move' : 'structure.drag.copy')}</small></div></div>}

      {context && <Menu labelKey={context.kind === 'drop' ? 'context.dropTitle' : 'context.title'} style={{ left: context.x, top: context.y }} onClose={() => setContext(null)}>{resolveActions(context).map(({ action, enabled, reasonKey }) => <MenuItem key={action.id} disabled={!enabled} disabledReasonKey={reasonKey} onSelect={() => choose(action.id)}>{t(action.labelKey)}</MenuItem>)}</Menu>}

      <Dialog open={previewIntent !== null} titleKey="dialog.previewTitle" onClose={() => { setPreview(null); setProblemKey(null) }}>
        <div className="structure-preview-summary"><div><small>{t('structure.multiInspector', { count: previewIntent?.source.length ?? 0 })}</small><strong>{previewIntent?.source.map((item) => item.name).join(', ')}</strong></div>{previewIntent?.destination && <div><small>{t('actions.target')}</small><strong>{previewIntent.destination.name}</strong></div>}</div>
        <p>{t('dialog.noMutation')}</p><p>{previewAction ? t(previewAction.descriptionKey) : null}</p>
        {previewAction?.requiresTarget && !previewIntent?.destination && <Select labelKey="actions.target" value="" onChange={(event) => { const target = targetCandidates.find((item) => item.id === event.target.value); if (target && previewIntent) setPreview(createActionIntent(previewIntent.actionId, previewIntent.source, target)) }}><option value="">{t('actions.target.choose')}</option>{targetCandidates.map((item) => <option key={`${item.guildId}:${item.id}`} value={item.id}>{item.name}</option>)}</Select>}
        {problemKey && <p role="alert">{t(problemKey, { requestId: 'unknown' })}</p>}
        <Button labelKey="common.preview" variant="primary" disabled={!previewAvailability?.enabled || Boolean(previewAction?.requiresTarget && !previewIntent?.destination)} disabledReasonKey={previewAvailability?.reasonKey ?? 'actions.disabled.target'} onClick={() => void execute()} />
      </Dialog>
    </section>
  )
}

function toggleExpanded(setter: React.Dispatch<React.SetStateAction<Set<string>>>, id: string) {
  setter((current) => { const next = new Set(current); if (next.has(id)) next.delete(id); else next.add(id); return next })
}

type ResourceItemProps = {
  item: Channel
  level?: number
  selected: boolean
  expanded: boolean
  dropHoverKey: string | null
  renameDraft: RenameDraft | null
  children?: ReactNode
  onToggle: () => void
  onSelect: (value: ResourceRef[]) => void
  onLabelClick: (source: ResourceRef, event: ReactMouseEvent) => void
  onMenu: (source: ResourceRef[], x: number, y: number, kind: 'object'|'drop', destination?: ResourceRef) => void
  onRename: (source: ResourceRef) => void
  onRenameChange: (value: string) => void
  onRenameSubmit: () => void
  onRenameCancel: () => void
  onPointerDown: (event: ReactPointerEvent, source: ResourceRef) => void
  onPointerMove: (event: ReactPointerEvent) => void
  onPointerUp: (event: ReactPointerEvent) => void
  onPointerCancel: () => void
}

function ResourceItem({ item, level = 1, selected, expanded, dropHoverKey, renameDraft, children, onToggle, onSelect, onLabelClick, onMenu, onRename, onRenameChange, onRenameSubmit, onRenameCancel, onPointerDown, onPointerMove, onPointerUp, onPointerCancel }: ResourceItemProps) {
  const { t } = useTranslation()
  const source = resourceRef(item)
  const hasChildren = Boolean(children)
  const key = dropKey(source)
  const typeKey = source.type === 'CATEGORY' ? 'resource.category' : source.type === 'THREAD' ? 'resource.thread' : 'resource.channel'
  const icon = source.type === 'CATEGORY' ? '▰' : source.type === 'THREAD' ? '↳' : [2,13].includes(item.type) ? '◖' : item.type === 15 ? '▤' : '#'
  const editing = renameDraft?.source.id === source.id
  function select(event: { ctrlKey?: boolean; metaKey?: boolean }) { const current = useInteractionStore.getState().selection; onSelect(event.ctrlKey || event.metaKey ? selected ? current.filter((entry) => entry.id !== source.id) : [...current, source] : [source]) }
  function keyboard(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key === 'F2' && selected && source.type !== 'THREAD') { event.preventDefault(); event.stopPropagation(); onRename(source); return }
    if (!hasChildren) return
    if (event.key === 'ArrowRight' && !expanded) { event.preventDefault(); event.stopPropagation(); onToggle() } else if (event.key === 'ArrowLeft' && expanded) { event.preventDefault(); event.stopPropagation(); onToggle() }
  }
  return (
    <TreeItem level={level} selected={selected} expandable={hasChildren} aria-expanded={hasChildren ? expanded : undefined} className={`structure-resource ${selected ? 'selected' : ''} ${dropHoverKey === key ? 'drop-hover' : ''} resource-${source.type.toLowerCase()}`}
      data-drop-id={item.id} data-drop-guild={item.guild_id} data-drop-name={item.name} data-drop-type={source.type} data-drop-position={item.position} data-drop-parent={item.parent_id ?? ''}
      onClick={(event) => {
        event.stopPropagation()
        const label = document.elementFromPoint(event.clientX, event.clientY)?.closest('.resource-copy')
        if (label && event.currentTarget.contains(label)) onLabelClick(source, event)
        else select(event)
      }} onKeyDown={keyboard} onContextMenu={(event) => { event.preventDefault(); event.stopPropagation() }}
      onPointerDown={(event) => { event.stopPropagation(); onPointerDown(event, source) }} onPointerMove={(event) => { event.stopPropagation(); onPointerMove(event) }} onPointerUp={(event) => { event.stopPropagation(); onPointerUp(event) }} onPointerCancel={(event) => { event.stopPropagation(); onPointerCancel() }} onLostPointerCapture={(event) => { event.stopPropagation(); onPointerCancel() }}>
      <div className="structure-resource-row">
        <button type="button" className={`resource-expander ${hasChildren ? '' : 'placeholder'}`} tabIndex={-1} aria-label={hasChildren ? t(expanded ? 'structure.tree.collapse' : 'structure.tree.expand', { name: item.name }) : undefined} onPointerDown={(event) => event.stopPropagation()} onClick={(event) => { event.stopPropagation(); if (hasChildren) onToggle() }}>{hasChildren ? (expanded ? '⌄' : '›') : ''}</button>
        <span className="resource-kind-icon" aria-hidden="true">{icon}</span>{editing && renameDraft ? <NameEditor originalName={renameDraft.originalName} resourceType={source.type} value={renameDraft.value} busy={renameDraft.busy} onChange={onRenameChange} onSubmit={onRenameSubmit} onCancel={onRenameCancel} /> : <span className="resource-copy"><strong>{item.name}</strong><small>{t(typeKey)} · {item.id}</small></span>}
        {source.type === 'CATEGORY' && <span className="resource-count">{(item as Channel & { channels?: Channel[] }).channels?.length ?? 0}</span>}
        {item.freshness !== 'FRESH' && <span className="resource-freshness-dot" title={t('common.stale')} />}
        <button type="button" className="resource-more" aria-label={t('structure.tree.actions')} onPointerDown={(event) => event.stopPropagation()} onClick={(event) => { event.stopPropagation(); const rect = event.currentTarget.getBoundingClientRect(); onMenu([source], rect.left, rect.bottom + 5, 'object') }}>•••</button>
      </div>
      {hasChildren && <div role="group" hidden={!expanded} className="structure-resource-children">{children}</div>}
    </TreeItem>
  )
}

function Inspector({ selection, item, capabilities, onActions }: { selection: ResourceRef[]; item: Channel | undefined; capabilities: DashboardCapabilities; onActions: (anchor: HTMLElement) => void }) {
  const { t } = useTranslation()
  if (selection.length === 0) return <div className="inspector-empty"><span aria-hidden="true">◇</span><p>{t('structure.selection.none')}</p><small>{t('structure.selection.help')}</small></div>
  if (selection.length > 1) return <div className="inspector-multi"><div className="inspector-title"><div><p className="eyebrow">{t('structure.properties')}</p><h2>{t('structure.multiInspector', { count: selection.length })}</h2></div><Badge>{selection.length}</Badge></div><div className="inspector-selection-list">{selection.map((resource) => <div key={resource.id}><span className="resource-kind-icon" aria-hidden="true">{resource.type === 'CATEGORY' ? '▰' : '#'}</span><span>{resource.name}</span></div>)}</div><button type="button" className="inspector-primary-action" onClick={(event) => onActions(event.currentTarget)}>{t('structure.selection.actions')}</button></div>
  const selected = selection[0]
  const typeKey = selected?.type === 'CATEGORY' ? 'resource.category' : selected?.type === 'THREAD' ? 'resource.thread' : 'resource.channel'
  const structureWrite = capabilities.user_capabilities['structure.write']?.outcome ?? capabilities.scoped_capabilities.capabilities['structure.write']?.outcome ?? 'UNKNOWN'
  return <div className="inspector-single"><div className="inspector-title"><div><p className="eyebrow">{t('structure.properties')}</p><h2>{selected?.name}</h2></div><Badge tone={item?.freshness === 'FRESH' ? 'ok' : 'warning'}>{item?.freshness === 'FRESH' ? t('structure.current') : t('structure.stale')}</Badge></div><div className="inspector-resource-hero"><span className="resource-kind-icon large" aria-hidden="true">{selected?.type === 'CATEGORY' ? '▰' : selected?.type === 'THREAD' ? '↳' : '#'}</span><div><strong>{t(typeKey)}</strong><small>{t('structure.inspector.identity')}</small></div></div><dl className="inspector-grid"><div><dt>{t('structure.inspector.discordId')}</dt><dd>{selected?.id}</dd></div><div><dt>{t('structure.inspector.type')}</dt><dd>{t(typeKey)}</dd></div><div><dt>{t('structure.inspector.parent')}</dt><dd>{item?.parent_id ?? t('structure.rootLabel')}</dd></div><div><dt>{t('structure.inspector.position')}</dt><dd>{item?.position ?? selected?.position ?? '—'}</dd></div><div><dt>{t('structure.inspector.freshness')}</dt><dd>{item?.freshness ?? t('common.unknown')}</dd></div><div><dt>{t('structure.inspector.observability')}</dt><dd>{item?.observability ?? t('common.unknown')}</dd></div><div><dt>{t('structure.inspector.assertion')}</dt><dd>{item?.data_assertion ?? t('common.unknown')}</dd></div><div><dt>{t('structure.inspector.capability')}</dt><dd><Badge tone={structureWrite === 'CAN' ? 'ok' : structureWrite === 'CANNOT' ? 'danger' : 'warning'}>{structureWrite === 'UNKNOWN' ? t('common.unknown') : structureWrite}</Badge></dd></div></dl><button type="button" className="inspector-primary-action" onClick={(event) => onActions(event.currentTarget)}>{t('structure.selection.actions')}</button></div>
}

function DropTargetCard({ destination, hoverKey, title, subtitle, icon }: { destination: ResourceRef; hoverKey: string | null; title: string; subtitle: string; icon: string }) {
  return <div className={`destination-drop-card ${hoverKey === dropKey(destination) ? 'drop-hover' : ''}`} data-drop-id={destination.id} data-drop-guild={destination.guildId} data-drop-name={destination.name} data-drop-type={destination.type} data-drop-position={destination.position} data-drop-parent={destination.parentId ?? ''}><span className="destination-icon" aria-hidden="true">{icon}</span><span><strong>{title}</strong><small>{subtitle}</small></span></div>
}

function DestinationGuildCard({ guild, userId, hoverKey }: { guild: Guild; userId: DiscordSnowflake; hoverKey: string | null }) {
  const { t } = useTranslation()
  const structure = useStructure(userId, guild.guild_id)
  const destination: ResourceRef = { id: guild.guild_id, name: guild.name, type: 'GUILD', guildId: guild.guild_id }
  const [expanded, setExpanded] = useState(false)
  return <section className={`destination-guild ${expanded ? 'expanded' : ''}`}><div className={`destination-guild-row ${hoverKey === dropKey(destination) ? 'drop-hover' : ''}`} data-drop-id={guild.guild_id} data-drop-guild={guild.guild_id} data-drop-name={guild.name} data-drop-type="GUILD"><span className="destination-server-avatar">{guild.name.slice(0, 2).toUpperCase()}</span><span className="destination-server-copy"><strong>{guild.name}</strong><small>{t('structure.drop.copy', { name: guild.name })}</small></span><button type="button" aria-label={expanded ? t('structure.tree.collapse', { name: guild.name }) : t('structure.tree.expand', { name: guild.name })} onClick={() => setExpanded((value) => !value)}>{expanded ? '⌄' : '›'}</button></div>{expanded && <div className="destination-guild-tree">{structure.isLoading && <small>{t('structure.destinations.loading')}</small>}{structure.isError && <small>{t('structure.destinations.unavailable')}</small>}{structure.data?.categories.map((category) => <DropTargetCard key={category.id} destination={resourceRef(category)} hoverKey={hoverKey} title={category.name} subtitle={t('structure.drop.copy', { name: category.name })} icon="▰" />)}</div>}</section>
}
