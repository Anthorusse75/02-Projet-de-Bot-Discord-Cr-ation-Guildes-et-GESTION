import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ApiError } from '../../api/client'
import { useGuildDashboardCapabilities, useTranslationWorkspace } from '../../api/queries'
import type { CapabilityDecision, TranslationGroup } from '../../api/types'
import type { DashboardContext } from '../../app/AppShell'
import type { MessageKey } from '../../localization/catalog'
import { discordSnowflake } from '../../shared/discord-id'
import { Badge, Button, Dialog, EmptyState, ErrorState, Input, Menu, MenuItem, Select, Skeleton, Toast } from '../../shared/components/ui'
import { resolveActions, type ActionContext, type ActionId, type Availability, type ResourceRef } from '../interaction/actions'
import { createActionIntent, dispatchAction } from '../interaction/dispatcher'
import { PointerGestureManager } from '../interaction/gestures'
import './translations.css'

const topologyKeys = { HUB_AND_SPOKE: 'translations.topology.hub', FULL_MESH: 'translations.topology.mesh', CUSTOM: 'translations.topology.custom' } as const satisfies Record<string, MessageKey>
const policyKeys = { OPEN_ALL: 'translations.visibility.open', LANGUAGE_FILTERED: 'translations.visibility.language', SCOPE_AND_LANGUAGE: 'translations.visibility.scopeLanguage', CUSTOM: 'translations.visibility.custom' } as const satisfies Record<string, MessageKey>
const providerKeys = { READY: 'translations.provider.ready', DEGRADED: 'translations.provider.degraded', ERROR: 'translations.provider.error', DISABLED: 'translations.provider.disabled', UNKNOWN: 'translations.provider.unknown', MANUAL_CONFIGURATION_REQUIRED: 'translations.provider.manual' } as const satisfies Record<string, MessageKey>
const translationActionIds: readonly ActionId[] = ['CREATE_VARIANT', 'LINK_EXISTING_VARIANT', 'CLONE_UNLINKED', 'PREVIEW']

type ActionDraft = { actionId: ActionId; group: TranslationGroup; source: ResourceRef; destination?: ResourceRef }

function translatedKey(values: Readonly<Record<string, MessageKey>>, value: string, fallback: MessageKey): MessageKey { return values[value] ?? fallback }
function groupRef(group: TranslationGroup): ResourceRef { return { id: group.id, name: group.name, type: 'TRANSLATION_GROUP', guildId: group.guild_id } }
function languageRef(group: TranslationGroup, languageId: string): ResourceRef | undefined {
  const language = group.languages.find((item) => item.id === languageId && item.enabled)
  return language ? { id: language.id, name: language.display_name, type: 'LANGUAGE_TARGET', guildId: group.guild_id, parentId: group.id } : undefined
}

export function TranslationWorkspace() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { me, guild, guilds, capabilities } = useOutletContext<DashboardContext>()
  const query = useTranslationWorkspace(me.user.discord_user_id, guild.guild_id)
  const destinationGuilds = guilds.filter((item) => item.guild_id !== guild.guild_id && item.installation_status === 'ACTIVE')
  const destinationQueries = useGuildDashboardCapabilities(me.user.discord_user_id, destinationGuilds.map((item) => item.guild_id))
  const destinationCapabilities = new Map(destinationGuilds.map((item, index) => [item.guild_id, destinationQueries[index]?.data]))
  const gestures = useRef(new PointerGestureManager())
  const [menu, setMenu] = useState<{ x: number; y: number; draft: ActionDraft; actions: Availability[] } | null>(null)
  const [draft, setDraft] = useState<ActionDraft | null>(null)
  const [desiredName, setDesiredName] = useState('')
  const [channelGroupId, setChannelGroupId] = useState('')
  const [discordResourceId, setDiscordResourceId] = useState('')
  const [problemKey, setProblemKey] = useState<'errors.authorization.denied' | 'errors.generic' | null>(null)
  const [feedbackKey, setFeedbackKey] = useState<'translations.action.planReady' | 'translations.action.linkReady' | 'translations.action.cloneReady' | null>(null)
  const [previewResult, setPreviewResult] = useState<Record<string, unknown> | null>(null)

  useEffect(() => {
    const cancel = (event: KeyboardEvent) => { if (event.key === 'Escape' && gestures.current.cancel()) setMenu(null) }
    document.addEventListener('keydown', cancel)
    return () => document.removeEventListener('keydown', cancel)
  }, [])

  if (query.isLoading) return <Skeleton />
  if (query.isError) return <ErrorState retry={() => void query.refetch()} />
  const data = query.data
  if (!data) return <EmptyState messageKey="translations.empty" />
  const workspace = data

  function providerDecision(group: TranslationGroup): CapabilityDecision {
    const binding = workspace.providers.find((item) => item.id === group.provider_binding_id)
    if (!binding || binding.status !== 'READY') return { outcome: 'CANNOT', causes: ['PROVIDER_NOT_READY'], remediations: [] }
    const key = { HUB_AND_SPOKE: 'supports_hub_and_spoke', FULL_MESH: 'supports_full_mesh', CUSTOM: 'supports_custom' }[group.routing_mode]
    const maximum = binding.capabilities_json.max_languages_per_group
    const withinLimit = typeof maximum !== 'number' || group.languages.length <= maximum
    const supported = key ? binding.capabilities_json[key] : undefined
    return { outcome: supported === true && withinLimit ? 'CAN' : supported === false || !withinLimit ? 'CANNOT' : 'UNKNOWN', causes: [], remediations: [] }
  }

  function actionContext(group: TranslationGroup, destination?: ResourceRef): ActionContext {
    const source = groupRef(group)
    const destinationGuild = destination ? guilds.find((item) => item.guild_id === destination.guildId) : undefined
    const destinationCapability = destination?.guildId === guild.guild_id ? capabilities : destination ? destinationCapabilities.get(destination.guildId) : undefined
    return {
      source: [source],
      ...(destination ? { destination } : {}),
      sourceUserCapabilities: capabilities?.user_capabilities ?? {},
      sourceBotCapabilities: capabilities?.bot_operations ?? {},
      ...(destinationCapability ? { destinationUserCapabilities: destinationCapability.user_capabilities, destinationBotCapabilities: destinationCapability.bot_operations } : {}),
      ...(destinationGuild ? { destinationInstallationStatus: destinationGuild.installation_status } : {}),
      providerCapabilities: { ROUTING_SUPPORTED: providerDecision(group) },
    }
  }

  function targetAt(x: number, y: number): ResourceRef | undefined {
    const selector = '[data-translation-target-type]'
    const hit = document.elementFromPoint?.(x, y)?.closest<HTMLElement>(selector)
    const element = hit ?? [...document.querySelectorAll<HTMLElement>(selector)].find((candidate) => {
      const rectangle = candidate.getBoundingClientRect()
      return x >= rectangle.left && x <= rectangle.right && y >= rectangle.top && y <= rectangle.bottom
    })
    const type = element?.dataset.translationTargetType as ResourceRef['type'] | undefined
    const id = element?.dataset.translationTargetId
    const targetGuild = element?.dataset.translationTargetGuild
    if (!type || !id || !targetGuild) return undefined
    return {
      id,
      name: element.dataset.translationTargetName ?? id,
      type,
      guildId: discordSnowflake(targetGuild),
      ...(element.dataset.translationTargetParent ? { parentId: element.dataset.translationTargetParent } : {}),
    }
  }

  function openActions(event: ReactPointerEvent, group: TranslationGroup) {
    const result = gestures.current.finish(event.nativeEvent)
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
    if (!result || !['context', 'right-drag'].includes(result.kind)) return
    const destination = result.kind === 'right-drag' ? targetAt(result.x, result.y) : undefined
    const source = groupRef(group)
    const contextual = { source, group, ...(destination ? { destination } : {}) }
    const menuX = Math.max(8, Math.min(result.x, window.innerWidth - 248))
    const menuY = Math.max(8, Math.min(result.y, window.innerHeight - 240))
    setMenu({ x: menuX, y: menuY, draft: { actionId: 'PREVIEW', ...contextual }, actions: resolveActions(actionContext(group, destination)) })
  }

  function beginAction(actionId: ActionId, group: TranslationGroup, destination?: ResourceRef) {
    setMenu(null)
    setProblemKey(null)
    setPreviewResult(null)
    const language = destination?.type === 'LANGUAGE_TARGET' ? group.languages.find((item) => item.id === destination.id) : group.languages.find((item) => item.enabled)
    const channelGroup = group.channel_groups[0]
    setDesiredName(group.root_kind === 'CATEGORY_SET' ? `${language?.display_name ?? group.name}` : `${channelGroup?.display_name ?? group.name}-${language?.code ?? 'variant'}`)
    setChannelGroupId(channelGroup?.id ?? '')
    setDiscordResourceId('')
    setDraft({ actionId, group, source: groupRef(group), ...(destination ? { destination } : {}) })
  }

  function chooseDestination(value: string) {
    if (!draft) return
    const destination = draft.actionId === 'CLONE_UNLINKED'
      ? destinationGuilds.filter((item) => item.guild_id === value).map((item) => ({ id: item.guild_id, name: item.name, type: 'GUILD' as const, guildId: item.guild_id }))[0]
      : languageRef(draft.group, value)
    setDraft({ ...draft, ...(destination ? { destination } : {}) })
    const language = draft.group.languages.find((item) => item.id === value)
    if (language && draft.actionId === 'CREATE_VARIANT') setDesiredName(draft.group.root_kind === 'CATEGORY_SET' ? language.display_name : `${draft.group.channel_groups.find((item) => item.id === channelGroupId)?.display_name ?? draft.group.name}-${language.code}`)
  }

  async function execute() {
    if (!draft) return
    const availability = resolveActions(actionContext(draft.group, draft.destination)).find((item) => item.action.id === draft.actionId)
    if (!availability?.enabled) { setProblemKey('errors.authorization.denied'); return }
    const variantType = draft.group.root_kind === 'CATEGORY_SET' ? 'CATEGORY' as const : 'CHANNEL' as const
    const intent = createActionIntent(draft.actionId, [draft.source], draft.destination, {
      variantType,
      desiredName,
      ...(variantType === 'CHANNEL' ? { translationChannelGroupId: channelGroupId } : {}),
      ...(discordResourceId ? { discordResourceId } : {}),
    })
    try {
      const result = await dispatchAction(intent, guild.guild_id, 'PREVIEW')
      if (result.kind === 'PREVIEW') { setPreviewResult(result.group); return }
      setDraft(null)
      if (result.kind === 'LINK') { setFeedbackKey('translations.action.linkReady'); await query.refetch(); return }
      if (result.kind === 'PLAN') setFeedbackKey('translations.action.planReady')
      if (result.kind === 'TRANSFER') setFeedbackKey('translations.action.cloneReady')
      navigate(result.path)
    } catch (error) {
      setProblemKey(error instanceof ApiError && error.status === 403 ? 'errors.authorization.denied' : 'errors.generic')
    }
  }

  const selectedAction = draft ? resolveActions(actionContext(draft.group, draft.destination)).find((item) => item.action.id === draft.actionId) : undefined
  const requiresLanguage = draft?.actionId === 'CREATE_VARIANT' || draft?.actionId === 'LINK_EXISTING_VARIANT'
  const requiresChannelGroup = requiresLanguage && draft?.group.root_kind !== 'CATEGORY_SET'
  const canExecute = Boolean(selectedAction?.enabled && (!selectedAction.action.requiresTarget || draft?.destination) && (!requiresChannelGroup || channelGroupId) && (draft?.actionId !== 'CREATE_VARIANT' || desiredName) && (draft?.actionId !== 'LINK_EXISTING_VARIANT' || discordResourceId))
  const previewLanguages = Array.isArray(previewResult?.languages) ? previewResult.languages.length : 0
  const previewVariants = [...(Array.isArray(previewResult?.category_variants) ? previewResult.category_variants : []), ...(Array.isArray(previewResult?.channel_variants) ? previewResult.channel_variants : [])].length
  const missingCount = data.groups.flatMap((group) => [...group.category_variants, ...group.channel_variants]).filter((item) => item.state === 'MISSING').length

  return <section className="translation-workspace">
    <div className="page-heading"><div><p className="eyebrow">{t('translations.eyebrow')}</p><h1>{t('translations.title')}</h1></div><Badge tone={missingCount ? 'danger' : 'ok'}>{t(missingCount ? 'translations.drift.detected' : 'translations.drift.clear', { count: missingCount })}</Badge></div>
    {feedbackKey && <Toast>{t(feedbackKey)}</Toast>}
    <div className="translation-summary" aria-label={t('translations.summary')}><article><strong>{data.languages.length}</strong><span>{t('translations.languages')}</span></article><article><strong>{data.groups.length}</strong><span>{t('translations.groups')}</span></article><article><strong>{data.visibility_bindings.length}</strong><span>{t('translations.scopeBindings')}</span></article><article><strong>{data.resource_language_policies.length}</strong><span>{t('translations.policies')}</span></article></div>
    <section><h2>{t('translations.languages')}</h2>{data.languages.length === 0 ? <EmptyState messageKey="translations.languages.empty" /> : <ul className="language-list">{data.languages.map((language) => <li key={language.id}><span>{language.emoji} {language.display_name}</span><Badge tone={language.enabled ? 'ok' : 'warning'}>{t(language.enabled ? 'translations.language.enabled' : 'translations.language.disabled')}</Badge></li>)}</ul>}</section>
    <section><h2>{t('translations.groups')}</h2>{data.groups.length === 0 ? <EmptyState messageKey="translations.empty" /> : <div className="translation-groups">{data.groups.map((group) => {
      const source = groupRef(group)
      const available = resolveActions(actionContext(group))
      const binding = data.providers.find((item) => item.id === group.provider_binding_id)
      return <article key={group.id} className="translation-group" tabIndex={0} data-translation-source={group.id} onContextMenu={(event) => event.preventDefault()} onPointerDown={(event) => { if ((event.target as HTMLElement).closest('button,input,select')) return; gestures.current.start(event.nativeEvent, source); event.currentTarget.setPointerCapture?.(event.pointerId) }} onPointerMove={(event) => { if (gestures.current.move(event.nativeEvent)) event.preventDefault() }} onPointerUp={(event) => openActions(event, group)} onPointerCancel={() => gestures.current.cancel()}>
        <header><div><h3>{group.name}</h3><Badge>{t(translatedKey(topologyKeys, group.routing_mode, 'common.unknown'))}</Badge></div><span>{t('translations.version', { version: group.version })}</span></header>
        <dl><div><dt>{t('translations.visibilityScope')}</dt><dd>{group.visibility_scope_id ? t('translations.visibility.scoped') : t('translations.visibility.open')}</dd></div><div><dt>{t('translations.provider')}</dt><dd>{binding ? t(translatedKey(providerKeys, binding.status, 'common.unknown')) : t('translations.provider.unbound')}</dd></div></dl>
        <div className="variant-hierarchy"><h4>{t('translations.hierarchy')}</h4>{group.channel_groups.map((channelGroup) => <div key={channelGroup.id}><strong>{channelGroup.display_name}</strong><ul>{group.channel_variants.filter((variant) => variant.translation_channel_group_id === channelGroup.id).map((variant) => <li key={variant.id}>{data.languages.find((language) => language.id === variant.language_profile_id)?.display_name ?? t('common.unknown')} <Badge tone={variant.state === 'MISSING' ? 'danger' : 'neutral'}>{t(variant.state === 'MISSING' ? 'translations.variant.missing' : 'translations.variant.active')}</Badge></li>)}</ul></div>)}</div>
        <div><h4>{t('translations.routes')}</h4>{group.routes.length ? <ul>{group.routes.map((route) => <li key={route.id}>{data.languages.find((item) => item.id === route.source_language_profile_id)?.display_name ?? t('common.unknown')} → {data.languages.find((item) => item.id === route.destination_language_profile_id)?.display_name ?? t('common.unknown')}</li>)}</ul> : <p>{t('translations.routes.empty')}</p>}</div>
        <div className="translation-targets" aria-label={t('translations.languageTargets')}>{group.languages.filter((language) => language.enabled).map((language) => <button type="button" key={language.id} data-translation-target-type="LANGUAGE_TARGET" data-translation-target-id={language.id} data-translation-target-guild={group.guild_id} data-translation-target-parent={group.id} data-translation-target-name={language.display_name}>{language.display_name}</button>)}</div>
        <div className="translation-actions" aria-label={t('translations.actions')}>{available.filter(({ action }) => translationActionIds.includes(action.id)).map(({ action, enabled, reasonKey }) => <Button key={action.id} labelKey={action.labelKey} disabled={!enabled} {...(reasonKey ? { disabledReasonKey: reasonKey } : {})} onClick={() => beginAction(action.id, group)} />)}</div>
      </article>
    })}</div>}</section>
    <section><h2>{t('translations.guildTargets')}</h2><div className="translation-targets">{destinationGuilds.map((item) => <button type="button" key={item.guild_id} data-translation-target-type="GUILD" data-translation-target-id={item.guild_id} data-translation-target-guild={item.guild_id} data-translation-target-name={item.name}>{item.name}</button>)}</div></section>
    <section><h2>{t('translations.visibility')}</h2>{data.resource_language_policies.length === 0 ? <p>{t('translations.visibility.none')}</p> : <ul>{data.resource_language_policies.map((policy) => <li key={policy.id}>{t(policy.resource_type === 'CATEGORY' ? 'resource.category' : 'resource.channel')} · {t(translatedKey(policyKeys, policy.visibility_policy, 'common.unknown'))} · {policy.inherit_language ? t('translations.inheritance.category') : t('translations.inheritance.self')}</li>)}</ul>}</section>
    <section><h2>{t('translations.provider')}</h2>{data.providers.length === 0 ? <p>{t('translations.provider.none')}</p> : <ul>{data.providers.map((provider) => <li key={provider.id}><Badge tone={provider.status === 'READY' ? 'ok' : provider.status === 'ERROR' ? 'danger' : 'warning'}>{t(translatedKey(providerKeys, provider.status, 'common.unknown'))}</Badge>{provider.status === 'MANUAL_CONFIGURATION_REQUIRED' && <span>{t('translations.provider.manualHelp')}</span>}</li>)}</ul>}</section>
    <section><h2>{t('translations.capacity')}</h2><p>{t('translations.capacity.roles', { count: data.visibility_bindings.length, limit: 250 })}</p><p>{t('translations.capacity.overwrites', { count: data.resource_language_policies.length, limit: 1000 })}</p></section>
    {menu && <Menu labelKey="context.title" style={{ left: menu.x, top: menu.y }} onClose={() => setMenu(null)}>{menu.actions.filter(({ action }) => translationActionIds.includes(action.id)).map(({ action, enabled, reasonKey }) => <MenuItem key={action.id} disabled={!enabled} disabledReasonKey={reasonKey} onSelect={() => beginAction(action.id, menu.draft.group, menu.draft.destination)}>{t(action.labelKey)}</MenuItem>)}</Menu>}
    <Dialog open={draft !== null} titleKey="translations.action.dialog" onClose={() => { setDraft(null); setProblemKey(null); setPreviewResult(null) }}>
      {draft && <>
        <p>{t('translations.action.source', { name: draft.group.name })}</p>
        {requiresLanguage && <Select labelKey="translations.languageTarget" value={draft.destination?.id ?? ''} onChange={(event) => chooseDestination(event.target.value)}><option value="">{t('actions.target.choose')}</option>{draft.group.languages.filter((item) => item.enabled).map((language) => <option key={language.id} value={language.id}>{language.display_name}</option>)}</Select>}
        {draft.actionId === 'CLONE_UNLINKED' && <Select labelKey="clone.destination" value={draft.destination?.guildId ?? ''} onChange={(event) => chooseDestination(event.target.value)}><option value="">{t('actions.target.choose')}</option>{destinationGuilds.map((item) => <option key={item.guild_id} value={item.guild_id}>{item.name}</option>)}</Select>}
        {draft.actionId === 'CREATE_VARIANT' && <Input labelKey="translations.desiredName" value={desiredName} maxLength={100} onChange={(event) => setDesiredName(event.target.value)} />}
        {requiresChannelGroup && <Select labelKey="translations.channelGroup" value={channelGroupId} onChange={(event) => setChannelGroupId(event.target.value)}><option value="">{t('actions.target.choose')}</option>{draft.group.channel_groups.map((item) => <option key={item.id} value={item.id}>{item.display_name}</option>)}</Select>}
        {draft.actionId === 'LINK_EXISTING_VARIANT' && <Input labelKey="translations.discordResourceId" value={discordResourceId} pattern="[1-9][0-9]{0,19}" onChange={(event) => setDiscordResourceId(event.target.value)} />}
        {previewResult && <div role="status"><p>{t('translations.previewSummary', { languages: previewLanguages, variants: previewVariants })}</p><p>{t(translatedKey(topologyKeys, String(previewResult.routing_mode ?? ''), 'common.unknown'))}</p></div>}
        {problemKey && <p role="alert">{t(problemKey, { requestId: 'unknown' })}</p>}
        <Button labelKey={draft.actionId === 'PREVIEW' ? 'common.preview' : 'common.confirm'} variant="primary" disabled={!canExecute} disabledReasonKey={selectedAction?.reasonKey ?? 'actions.disabled.target'} onClick={() => void execute()} />
      </>}
    </Dialog>
  </section>
}
