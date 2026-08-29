import { useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useTranslationWorkspace } from '../../api/queries'
import type { CapabilityDecision, TranslationGroup } from '../../api/types'
import type { DashboardContext } from '../../app/AppShell'
import type { MessageKey } from '../../localization/catalog'
import { Badge, Button, EmptyState, ErrorState, Menu, MenuItem, Skeleton } from '../../shared/components/ui'
import { resolveActions, type Availability, type ResourceRef } from '../interaction/actions'
import { createActionIntent, dispatchAction } from '../interaction/dispatcher'
import { PointerGestureManager } from '../interaction/gestures'
import './translations.css'

const topologyKeys = { HUB_AND_SPOKE: 'translations.topology.hub', FULL_MESH: 'translations.topology.mesh', CUSTOM: 'translations.topology.custom' } as const satisfies Record<string, MessageKey>
const policyKeys = { OPEN_ALL: 'translations.visibility.open', LANGUAGE_FILTERED: 'translations.visibility.language', SCOPE_AND_LANGUAGE: 'translations.visibility.scopeLanguage', CUSTOM: 'translations.visibility.custom' } as const satisfies Record<string, MessageKey>
const providerKeys = { READY: 'translations.provider.ready', DEGRADED: 'translations.provider.degraded', ERROR: 'translations.provider.error', DISABLED: 'translations.provider.disabled', UNKNOWN: 'translations.provider.unknown', MANUAL_CONFIGURATION_REQUIRED: 'translations.provider.manual' } as const satisfies Record<string, MessageKey>

function translatedKey(values: Readonly<Record<string, MessageKey>>, value: string, fallback: MessageKey): MessageKey { return values[value] ?? fallback }

export function TranslationWorkspace() {
  const { t } = useTranslation(); const navigate = useNavigate(); const { me, guild, capabilities } = useOutletContext<DashboardContext>()
  const query = useTranslationWorkspace(me.user.discord_user_id, guild.guild_id); const gestures = useRef(new PointerGestureManager())
  const [menu, setMenu] = useState<{ x: number; y: number; source: ResourceRef; actions: Availability[] } | null>(null)
  if (query.isLoading) return <Skeleton />
  if (query.isError) return <ErrorState retry={() => void query.refetch()} />
  const data = query.data
  if (!data) return <EmptyState messageKey="translations.empty" />
  const providerDecision: CapabilityDecision = { outcome: data.providers.some((item) => item.status === 'READY') ? 'CAN' : data.providers.some((item) => item.status === 'MANUAL_CONFIGURATION_REQUIRED' || item.status === 'ERROR') ? 'CANNOT' : 'UNKNOWN', causes: [], remediations: [] }
  function resource(group: TranslationGroup): ResourceRef { return { id: group.id, name: group.name, type: 'TRANSLATION_GROUP', guildId: guild.guild_id } }
  function actionContext(source: ResourceRef) { return { source: [source], sourceUserCapabilities: capabilities?.user_capabilities ?? {}, sourceBotCapabilities: capabilities?.bot_operations ?? {}, providerCapabilities: { ROUTING_SUPPORTED: providerDecision } } }
  function openActions(event: ReactPointerEvent, group: TranslationGroup) { const result = gestures.current.finish(event.nativeEvent); event.currentTarget.releasePointerCapture?.(event.pointerId); if (!result || !['context', 'right-drag'].includes(result.kind)) return; const source = resource(group); setMenu({ x: result.x, y: result.y, source, actions: resolveActions(actionContext(source)) }) }
  async function choose(actionId: string, source: ResourceRef) { setMenu(null); const result = await dispatchAction(createActionIntent(actionId, [source]), guild.guild_id, 'PREVIEW'); navigate(result.path) }
  const missingCount = data.groups.flatMap((group) => [...group.category_variants, ...group.channel_variants]).filter((item) => item.state === 'MISSING').length
  return <section className="translation-workspace">
    <div className="page-heading"><div><p className="eyebrow">{t('translations.eyebrow')}</p><h1>{t('translations.title')}</h1></div><Badge tone={missingCount ? 'danger' : 'ok'}>{t(missingCount ? 'translations.drift.detected' : 'translations.drift.clear', { count: missingCount })}</Badge></div>
    <div className="translation-summary" aria-label={t('translations.summary')}><article><strong>{data.languages.length}</strong><span>{t('translations.languages')}</span></article><article><strong>{data.groups.length}</strong><span>{t('translations.groups')}</span></article><article><strong>{data.visibility_bindings.length}</strong><span>{t('translations.scopeBindings')}</span></article><article><strong>{data.resource_language_policies.length}</strong><span>{t('translations.policies')}</span></article></div>
    <section><h2>{t('translations.languages')}</h2>{data.languages.length === 0 ? <EmptyState messageKey="translations.languages.empty" /> : <ul className="language-list">{data.languages.map((language) => <li key={language.id}><span>{language.emoji} {language.display_name}</span><Badge tone={language.enabled ? 'ok' : 'warning'}>{t(language.enabled ? 'translations.language.enabled' : 'translations.language.disabled')}</Badge></li>)}</ul>}</section>
    <section><h2>{t('translations.groups')}</h2>{data.groups.length === 0 ? <EmptyState messageKey="translations.empty" /> : <div className="translation-groups">{data.groups.map((group) => { const source = resource(group); const available = resolveActions(actionContext(source)); return <article key={group.id} className="translation-group" tabIndex={0} onContextMenu={(event) => event.preventDefault()} onPointerDown={(event) => { gestures.current.start(event.nativeEvent, source); event.currentTarget.setPointerCapture?.(event.pointerId) }} onPointerMove={(event) => { if (gestures.current.move(event.nativeEvent)) event.preventDefault() }} onPointerUp={(event) => openActions(event, group)} onPointerCancel={() => gestures.current.cancel()}>
      <header><div><h3>{group.name}</h3><Badge>{t(translatedKey(topologyKeys, group.routing_mode, 'common.unknown'))}</Badge></div><span>{t('translations.version', { version: group.version })}</span></header>
      <dl><div><dt>{t('translations.visibilityScope')}</dt><dd>{group.visibility_scope_id ? t('translations.visibility.scoped') : t('translations.visibility.open')}</dd></div><div><dt>{t('translations.provider')}</dt><dd>{group.provider_binding_id ? t('translations.provider.bound') : t('translations.provider.unbound')}</dd></div></dl>
      <div className="variant-hierarchy"><h4>{t('translations.hierarchy')}</h4>{group.channel_groups.map((channelGroup) => <div key={channelGroup.id}><strong>{channelGroup.display_name}</strong><ul>{group.channel_variants.filter((variant) => variant.translation_channel_group_id === channelGroup.id).map((variant) => <li key={variant.id}>{data.languages.find((language) => language.id === variant.language_profile_id)?.display_name ?? t('common.unknown')} <Badge tone={variant.state === 'MISSING' ? 'danger' : 'neutral'}>{t(variant.state === 'MISSING' ? 'translations.variant.missing' : 'translations.variant.active')}</Badge></li>)}</ul></div>)}</div>
      <div><h4>{t('translations.routes')}</h4>{group.routes.length ? <ul>{group.routes.map((route) => <li key={route.id}>{data.languages.find((item) => item.id === route.source_language_profile_id)?.display_name ?? t('common.unknown')} → {data.languages.find((item) => item.id === route.destination_language_profile_id)?.display_name ?? t('common.unknown')}</li>)}</ul> : <p>{t('translations.routes.empty')}</p>}</div>
      <div className="translation-actions" aria-label={t('translations.actions')}>{available.filter(({ action }) => ['CREATE_VARIANT','LINK_EXISTING_VARIANT','CLONE_UNLINKED','PREVIEW'].includes(action.id)).map(({ action, enabled, reasonKey }) => <Button key={action.id} labelKey={action.labelKey} disabled={!enabled} {...(reasonKey ? { disabledReasonKey: reasonKey } : {})} onClick={() => void choose(action.id, source)} />)}</div>
    </article>})}</div>}</section>
    <section><h2>{t('translations.visibility')}</h2>{data.resource_language_policies.length === 0 ? <p>{t('translations.visibility.none')}</p> : <ul>{data.resource_language_policies.map((policy) => <li key={policy.id}>{t(policy.resource_type === 'CATEGORY' ? 'resource.category' : 'resource.channel')} · {t(translatedKey(policyKeys, policy.visibility_policy, 'common.unknown'))} · {policy.inherit_language ? t('translations.inheritance.category') : t('translations.inheritance.self')}</li>)}</ul>}</section>
    <section><h2>{t('translations.provider')}</h2>{data.providers.length === 0 ? <p>{t('translations.provider.none')}</p> : <ul>{data.providers.map((provider) => <li key={provider.id}><Badge tone={provider.status === 'READY' ? 'ok' : provider.status === 'ERROR' ? 'danger' : 'warning'}>{t(translatedKey(providerKeys, provider.status, 'common.unknown'))}</Badge>{provider.status === 'MANUAL_CONFIGURATION_REQUIRED' && <span>{t('translations.provider.manualHelp')}</span>}</li>)}</ul>}</section>
    <section><h2>{t('translations.capacity')}</h2><p>{t('translations.capacity.roles', { count: data.visibility_bindings.length, limit: 250 })}</p><p>{t('translations.capacity.overwrites', { count: data.resource_language_policies.length, limit: 1000 })}</p></section>
    {menu && <Menu labelKey="context.title" style={{ left: menu.x, top: menu.y }} onClose={() => setMenu(null)}>{menu.actions.filter(({ action }) => ['CREATE_VARIANT','LINK_EXISTING_VARIANT','CLONE_UNLINKED','PREVIEW'].includes(action.id)).map(({ action, enabled, reasonKey }) => <MenuItem key={action.id} disabled={!enabled} disabledReasonKey={reasonKey} onSelect={() => void choose(action.id, menu.source)}>{t(action.labelKey)}</MenuItem>)}</Menu>}
  </section>
}
