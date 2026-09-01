import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useOutletContext } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ApiError, apiRequest } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import { useCampaignDeliveries, useCampaignTargets, useCampaigns } from '../../api/queries'
import type { Campaign, CampaignSchedule, CampaignSimulationReport, CampaignTargetKind, CampaignVariantPreview, ComponentActionRow, Embed, LogicalGroup, PublicationMode, ScheduleKind, Structure, TranslationPublicationMode, TranslationWorkspace } from '../../api/types'
import type { DashboardContext } from '../../app/AppShell'
import type { MessageKey } from '../../localization/catalog'
import { attachmentPolicyKey, blockedReasonKey, campaignErrorKey, campaignStatusKey, deliveryStatusKey, publicationModeKey, targetKindKey, translationPublicationModeKey, translationStateKey, variantOutcomeKey } from '../../localization/presentation'
import { Badge, Button, EmptyState, ErrorState, Input, Select, Skeleton, Status, Toast } from '../../shared/components/ui'
import { MessageModelEditor } from './MessageModelEditor'
import './campaigns.css'

const publicationModes: readonly PublicationMode[] = ['IMMEDIATE', 'ONE_SHOT_DEFERRED', 'RECURRING', 'EVENT_TRIGGERED']
const scheduledModes: readonly PublicationMode[] = ['ONE_SHOT_DEFERRED', 'RECURRING']
const targetKinds: readonly CampaignTargetKind[] = ['CHANNEL', 'LOGICAL_GROUP', 'TRANSLATION_GROUP']
const translationPublicationModes: readonly TranslationPublicationMode[] = ['SOURCE_ONLY', 'EXISTING_PROVIDER', 'DID_TRANSLATED_FANOUT', 'SELECTED_LANGUAGES']

function errorKey(error: unknown): MessageKey {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'errors.auth.required'
    if (error.status === 403) return 'errors.authorization.denied'
    return campaignErrorKey(error.problem.code)
  }
  return 'errors.generic'
}

export function CampaignCenter() {
  const { t } = useTranslation()
  const { me, guilds } = useOutletContext<DashboardContext>()
  const userId = me.user.discord_user_id
  const client = useQueryClient()
  const campaigns = useCampaigns(userId)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const selected = campaigns.data?.campaigns.find((item) => item.id === selectedId) ?? null

  const [name, setName] = useState('')
  const [sourceLanguage, setSourceLanguage] = useState('en')
  const [messageContent, setMessageContent] = useState('')
  const [createEmbeds, setCreateEmbeds] = useState<Embed[]>([])
  const [createActionRows, setCreateActionRows] = useState<ComponentActionRow[]>([])
  const [publicationMode, setPublicationMode] = useState<PublicationMode>('IMMEDIATE')
  const [problemKey, setProblemKey] = useState<MessageKey | null>(null)
  const [feedbackKey, setFeedbackKey] = useState<MessageKey | null>(null)

  const [editContent, setEditContent] = useState('')
  const [editEmbeds, setEditEmbeds] = useState<Embed[]>([])
  const [editActionRows, setEditActionRows] = useState<ComponentActionRow[]>([])
  const [editAllowEveryone, setEditAllowEveryone] = useState(false)

  const [targetKind, setTargetKind] = useState<CampaignTargetKind>('CHANNEL')
  const [targetGuildId, setTargetGuildId] = useState('')
  const [targetChannelId, setTargetChannelId] = useState('')
  const [targetLogicalGroupId, setTargetLogicalGroupId] = useState('')
  const [targetTranslationGroupId, setTargetTranslationGroupId] = useState('')
  const [targetTranslationMode, setTargetTranslationMode] = useState<TranslationPublicationMode>('SOURCE_ONLY')
  const [targetSelectedLanguageIds, setTargetSelectedLanguageIds] = useState<string[]>([])
  const targets = useCampaignTargets(userId, selected?.id)
  // A target may be created for any Guild the caller is authorized in, not
  // only the Guild currently active in the shell -- so these query the
  // real per-Guild channel/logical-group/translation-group state for
  // whichever destination Guild is picked in the "add target" form, never a
  // fake/static list. Each is only enabled once a destination Guild AND the
  // matching target kind are both selected -- never fired speculatively.
  const targetStructure = useQuery({
    enabled: Boolean(targetGuildId) && targetKind === 'CHANNEL',
    queryKey: ['did', userId, targetGuildId || 'none', 'campaign-target-structure'],
    queryFn: () => apiRequest<Structure>(`/api/v1/guilds/${targetGuildId}/structure`),
  })
  const targetChannels = targetStructure.data
    ? [...targetStructure.data.root_channels, ...targetStructure.data.categories.flatMap((category) => category.channels)]
    : []
  const targetLogicalGroups = useQuery({
    enabled: Boolean(targetGuildId) && targetKind === 'LOGICAL_GROUP',
    queryKey: ['did', userId, targetGuildId || 'none', 'campaign-target-logical-groups'],
    queryFn: () => apiRequest<{ groups: LogicalGroup[] }>(`/api/v1/guilds/${targetGuildId}/logical-groups`),
  })
  const targetTranslationWorkspace = useQuery({
    enabled: Boolean(targetGuildId) && targetKind === 'TRANSLATION_GROUP',
    queryKey: ['did', userId, targetGuildId || 'none', 'campaign-target-translation-workspace'],
    queryFn: () => apiRequest<TranslationWorkspace>(`/api/v1/guilds/${targetGuildId}/translation-workspace`),
  })
  const targetTranslationGroups = targetTranslationWorkspace.data?.groups ?? []
  const targetLanguageProfiles = targetTranslationWorkspace.data?.languages ?? []

  const [scheduleKind, setScheduleKind] = useState<ScheduleKind>('ONE_SHOT')
  const [fireAt, setFireAt] = useState('')
  const [startsAt, setStartsAt] = useState('')
  const [timezone, setTimezone] = useState('UTC')
  const [rrule, setRrule] = useState('')
  const [scheduleResult, setScheduleResult] = useState<CampaignSchedule | null>(null)

  const [simulation, setSimulation] = useState<CampaignSimulationReport | null>(null)
  const [simulating, setSimulating] = useState(false)

  const deliveries = useCampaignDeliveries(userId, selected?.id)

  const [variantLanguage, setVariantLanguage] = useState('')
  const [variantPreview, setVariantPreview] = useState<CampaignVariantPreview | null>(null)
  const [variantContent, setVariantContent] = useState('')

  const [resolvingDeliveryId, setResolvingDeliveryId] = useState<string | null>(null)
  const [resolveMessageId, setResolveMessageId] = useState('')
  const [editingDeliveryId, setEditingDeliveryId] = useState<string | null>(null)
  const [deliveryEditContent, setDeliveryEditContent] = useState('')

  useEffect(() => {
    if (!selected) return
    setEditContent(selected.message_model.content)
    setEditEmbeds(selected.message_model.embeds ?? [])
    setEditActionRows(selected.message_model.action_rows ?? [])
    setEditAllowEveryone(Boolean(selected.allowed_mentions_policy.allow_everyone))
  }, [selectedId])

  function selectCampaign(id: string) {
    setSelectedId(id); setProblemKey(null); setFeedbackKey(null)
    setSimulation(null); setScheduleResult(null); setVariantPreview(null); setVariantLanguage(''); setVariantContent('')
    setTargetKind('CHANNEL'); setTargetGuildId(''); setTargetChannelId('')
    setTargetLogicalGroupId(''); setTargetTranslationGroupId(''); setTargetTranslationMode('SOURCE_ONLY'); setTargetSelectedLanguageIds([])
  }

  function replaceCampaign(campaign: Campaign) {
    client.setQueryData<{campaigns:Campaign[]}>(queryKeys.campaigns(userId), (current) =>
      current ? { campaigns: current.campaigns.map((item) => item.id === campaign.id ? campaign : item) } : current)
  }

  async function createCampaign() {
    setProblemKey(null)
    try {
      const response = await apiRequest<{created:boolean;campaign:Campaign}>('/api/v1/campaigns', {
        method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() },
        body: { name, source_language_code: sourceLanguage, message_model: { content: messageContent, embeds: createEmbeds, action_rows: createActionRows }, allowed_mentions_policy: {}, publication_mode: publicationMode },
      })
      setFeedbackKey('campaigns.created')
      setName(''); setMessageContent(''); setCreateEmbeds([]); setCreateActionRows([])
      await campaigns.refetch()
      selectCampaign(response.campaign.id)
    } catch (error) { setProblemKey(errorKey(error)) }
  }

  async function saveDetail() {
    if (!selected) return
    setProblemKey(null)
    try {
      const response = await apiRequest<Campaign>(`/api/v1/campaigns/${selected.id}`, {
        method: 'PATCH',
        body: { expected_version: selected.version, message_model: { content: editContent, embeds: editEmbeds, action_rows: editActionRows }, allowed_mentions_policy: { allow_everyone: editAllowEveryone } },
      })
      replaceCampaign(response)
      setFeedbackKey('campaigns.detail.saved')
    } catch (error) { setProblemKey(errorKey(error)) }
  }

  function targetReady(): boolean {
    if (!targetGuildId) return false
    if (targetKind === 'CHANNEL') return Boolean(targetChannelId)
    if (targetKind === 'LOGICAL_GROUP') return Boolean(targetLogicalGroupId)
    // TRANSLATION_GROUP
    if (!targetTranslationGroupId) return false
    if (targetTranslationMode === 'SELECTED_LANGUAGES') return targetSelectedLanguageIds.length > 0
    return true
  }

  async function addTarget() {
    if (!selected || !targetReady()) return
    setProblemKey(null)
    try {
      const body: Record<string, unknown> = { guild_id: targetGuildId, target_kind: targetKind }
      if (targetKind === 'CHANNEL') body.discord_channel_id = targetChannelId
      else if (targetKind === 'LOGICAL_GROUP') body.logical_group_id = targetLogicalGroupId
      else {
        body.translation_group_id = targetTranslationGroupId
        body.translation_publication_mode = targetTranslationMode
        if (targetTranslationMode === 'SELECTED_LANGUAGES') body.selected_language_profile_ids = targetSelectedLanguageIds
      }
      await apiRequest(`/api/v1/campaigns/${selected.id}/targets`, {
        method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() }, body,
      })
      setFeedbackKey('campaigns.targets.added')
      setTargetChannelId(''); setTargetLogicalGroupId(''); setTargetTranslationGroupId(''); setTargetSelectedLanguageIds([])
      await targets.refetch()
    } catch (error) { setProblemKey(errorKey(error)) }
  }

  function toggleSelectedLanguage(id: string) {
    setTargetSelectedLanguageIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id])
  }

  async function createSchedule() {
    if (!selected) return
    setProblemKey(null)
    try {
      const body: Record<string, unknown> = { schedule_kind: scheduleKind, timezone: timezone || null }
      if (scheduleKind === 'ONE_SHOT') body.fire_at = fireAt ? new Date(fireAt).toISOString() : null
      else { body.rrule = rrule; body.starts_at = startsAt ? new Date(startsAt).toISOString() : null }
      const response = await apiRequest<CampaignSchedule>(`/api/v1/campaigns/${selected.id}/schedule`, {
        method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() }, body,
      })
      setScheduleResult(response)
      setFeedbackKey('campaigns.schedule.created')
    } catch (error) { setProblemKey(errorKey(error)) }
  }

  async function runSimulation() {
    if (!selected) return
    setProblemKey(null); setSimulating(true)
    try {
      const response = await apiRequest<CampaignSimulationReport>(`/api/v1/campaigns/${selected.id}/simulate`, { method: 'POST' })
      setSimulation(response)
    } catch (error) { setProblemKey(errorKey(error)) } finally { setSimulating(false) }
  }

  async function transition(action: 'activate'|'pause'|'resume'|'cancel') {
    if (!selected) return
    setProblemKey(null)
    try {
      const response = await apiRequest<{campaign:Campaign}|Campaign>(`/api/v1/campaigns/${selected.id}/${action}`, {
        method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() },
      })
      const campaign = 'campaign' in response ? response.campaign : response
      replaceCampaign(campaign)
      if (action === 'activate') setFeedbackKey('campaigns.lifecycle.activated')
    } catch (error) { setProblemKey(errorKey(error)) }
  }

  async function checkVariant() {
    if (!selected || !variantLanguage) return
    setProblemKey(null)
    try {
      const response = await apiRequest<CampaignVariantPreview>(`/api/v1/campaigns/${selected.id}/variants/${encodeURIComponent(variantLanguage)}`)
      setVariantPreview(response)
      setVariantContent(response.approved_variant?.localized_message_model.content ?? '')
    } catch (error) { setProblemKey(errorKey(error)) }
  }

  async function approveVariant() {
    if (!selected || !variantLanguage) return
    setProblemKey(null)
    try {
      await apiRequest(`/api/v1/campaigns/${selected.id}/variants/${encodeURIComponent(variantLanguage)}/approve`, {
        method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() },
        body: { localized_message_model: { content: variantContent, embeds: [] } },
      })
      setFeedbackKey('campaigns.variants.approved')
      await checkVariant()
    } catch (error) { setProblemKey(errorKey(error)) }
  }

  async function resolveIntervention(deliveryId: string, resolution: 'SENT' | 'FAILED') {
    if (!selected) return
    setProblemKey(null)
    try {
      const body: Record<string, unknown> = { resolution }
      if (resolution === 'SENT') body.discord_message_id = resolveMessageId
      await apiRequest(`/api/v1/campaigns/${selected.id}/deliveries/${deliveryId}/intervention/resolve`, {
        method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() }, body,
      })
      setFeedbackKey('campaigns.deliveries.resolved')
      setResolvingDeliveryId(null); setResolveMessageId('')
      await deliveries.refetch()
    } catch (error) { setProblemKey(errorKey(error)) }
  }

  async function requeueDelivery(deliveryId: string) {
    if (!selected) return
    setProblemKey(null)
    try {
      await apiRequest(`/api/v1/campaigns/${selected.id}/deliveries/${deliveryId}/requeue`, {
        method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() },
      })
      setFeedbackKey('campaigns.deliveries.requeued')
      await deliveries.refetch()
    } catch (error) { setProblemKey(errorKey(error)) }
  }

  async function editDelivery(deliveryId: string) {
    if (!selected) return
    setProblemKey(null)
    try {
      await apiRequest(`/api/v1/campaigns/${selected.id}/deliveries/${deliveryId}/edit`, {
        method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() },
        body: { message_model: { content: deliveryEditContent, embeds: [] } },
      })
      setFeedbackKey('campaigns.deliveries.edited')
      setEditingDeliveryId(null); setDeliveryEditContent('')
      await deliveries.refetch()
    } catch (error) { setProblemKey(errorKey(error)) }
  }

  async function deleteDelivery(deliveryId: string) {
    if (!selected) return
    setProblemKey(null)
    try {
      await apiRequest(`/api/v1/campaigns/${selected.id}/deliveries/${deliveryId}/delete`, {
        method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() },
      })
      setFeedbackKey('campaigns.deliveries.deleted')
      await deliveries.refetch()
    } catch (error) { setProblemKey(errorKey(error)) }
  }

  if (campaigns.isLoading) return <Skeleton />
  if (campaigns.isError) return <ErrorState retry={() => void campaigns.refetch()} />
  const list = campaigns.data?.campaigns ?? []
  const canActivate = selected?.lifecycle_status === 'DRAFT'
  const canPause = selected?.lifecycle_status === 'ACTIVE_RUNNING' || selected?.lifecycle_status === 'SCHEDULED_ARMED'
  const canResume = selected?.lifecycle_status === 'PAUSED'
  const canCancel = Boolean(selected) && selected?.lifecycle_status !== 'CANCELLED' && selected?.lifecycle_status !== 'COMPLETED'
  const canCreateSchedule = Boolean(selected) && selected !== null && scheduledModes.includes(selected.publication_mode)

  return <section className="campaign-center">
    <div className="page-heading"><div><p className="eyebrow">{t('campaigns.eyebrow')}</p><h1>{t('campaigns.title')}</h1></div></div>
    {feedbackKey && <Toast>{t(feedbackKey)}</Toast>}
    {problemKey && <p role="alert">{t(problemKey, { requestId: 'unknown' })}</p>}

    <section className="campaign-create">
      <h2>{t('campaigns.create')}</h2>
      <form onSubmit={(event) => { event.preventDefault(); void createCampaign() }}>
        <Input labelKey="campaigns.name" value={name} maxLength={200} required onChange={(event) => setName(event.target.value)} />
        <Input labelKey="campaigns.sourceLanguage" value={sourceLanguage} minLength={2} maxLength={16} required onChange={(event) => setSourceLanguage(event.target.value)} />
        <label className="field" htmlFor="campaign-create-content"><span>{t('campaigns.messageContent')}</span><textarea id="campaign-create-content" value={messageContent} maxLength={2000} required onChange={(event) => setMessageContent(event.target.value)} /></label>
        <MessageModelEditor idPrefix="campaign-create" embeds={createEmbeds} actionRows={createActionRows} onEmbedsChange={setCreateEmbeds} onActionRowsChange={setCreateActionRows} />
        <Select labelKey="campaigns.publicationMode" value={publicationMode} onChange={(event) => setPublicationMode(event.target.value as PublicationMode)}>
          {publicationModes.map((mode) => <option key={mode} value={mode}>{t(publicationModeKey(mode))}</option>)}
        </Select>
        <Button labelKey="campaigns.create" type="submit" variant="primary" disabled={!name || !messageContent} />
      </form>
    </section>

    <section className="campaign-list">
      <h2>{t('campaigns.list')}</h2>
      {list.length === 0 ? <EmptyState messageKey="campaigns.empty" /> : <div className="card-grid">{list.map((campaign) =>
        <button type="button" key={campaign.id} className={`campaign-card ${campaign.id === selectedId ? 'selected' : ''}`} onClick={() => selectCampaign(campaign.id)}>
          <strong>{campaign.name}</strong>
          <Badge tone={campaign.lifecycle_status === 'FAILED_INTERVENTION' ? 'danger' : campaign.lifecycle_status === 'ACTIVE_RUNNING' ? 'ok' : 'neutral'}>{t(campaignStatusKey(campaign.lifecycle_status))}</Badge>
          <span>{t(publicationModeKey(campaign.publication_mode))}</span>
          <span>{t('campaigns.version', { version: campaign.version })}</span>
        </button>)}</div>}
    </section>

    {selected && <section className="campaign-detail">
      <h2>{t('campaigns.detail')}</h2>
      <dl><div><dt>{t('campaigns.status')}</dt><dd><Badge>{t(campaignStatusKey(selected.lifecycle_status))}</Badge></dd></div>
        <div><dt>{t('campaigns.sourceLanguage')}</dt><dd>{selected.source_language_code}</dd></div>
        <div><dt>{t('campaigns.attachmentPolicy')}</dt><dd>{t(attachmentPolicyKey(selected.attachment_policy))}</dd></div></dl>
      <label className="field" htmlFor="campaign-edit-content"><span>{t('campaigns.messageContent')}</span><textarea id="campaign-edit-content" value={editContent} maxLength={2000} onChange={(event) => setEditContent(event.target.value)} /></label>
      <MessageModelEditor idPrefix="campaign-edit" embeds={editEmbeds} actionRows={editActionRows} onEmbedsChange={setEditEmbeds} onActionRowsChange={setEditActionRows} />
      <fieldset className="field"><legend>{t('campaigns.mentions')}</legend>
        <label><input type="checkbox" checked={!editAllowEveryone} onChange={() => setEditAllowEveryone(false)} /> {t('campaigns.mentions.none')}</label>
        <label><input type="checkbox" checked={editAllowEveryone} onChange={() => setEditAllowEveryone(true)} /> {t('campaigns.mentions.everyone')}</label>
      </fieldset>
      <Button labelKey="campaigns.detail.save" variant="primary" onClick={() => void saveDetail()} />

      <section className="campaign-targets">
        <h3>{t('campaigns.targets')}</h3>
        {targets.isLoading ? <Skeleton /> : (targets.data?.targets.length ?? 0) === 0 ? <EmptyState messageKey="campaigns.targets.empty" /> :
          <ul>{targets.data?.targets.map((target) => <li key={target.id}>
            <Badge>{t(targetKindKey(target.target_kind))}</Badge> {target.guild_id}
            {target.target_kind === 'CHANNEL' && ` / ${target.discord_channel_id ?? '—'}`}
            {target.target_kind === 'LOGICAL_GROUP' && ` / ${target.logical_group_id ?? '—'}`}
            {target.target_kind === 'TRANSLATION_GROUP' && <> / {target.translation_group_id ?? '—'} <Badge>{target.translation_publication_mode ? t(translationPublicationModeKey(target.translation_publication_mode)) : '—'}</Badge></>}
          </li>)}</ul>}
        <div className="target-form">
          <Select labelKey="campaigns.targets.kind" value={targetKind} onChange={(event) => { setTargetKind(event.target.value as CampaignTargetKind); setTargetChannelId(''); setTargetLogicalGroupId(''); setTargetTranslationGroupId('') }}>
            {targetKinds.map((kind) => <option key={kind} value={kind}>{t(targetKindKey(kind))}</option>)}
          </Select>
          <Select labelKey="campaigns.targets.guild" value={targetGuildId} onChange={(event) => { setTargetGuildId(event.target.value); setTargetChannelId(''); setTargetLogicalGroupId(''); setTargetTranslationGroupId('') }}>
            <option value="">{t('actions.target.choose')}</option>
            {guilds.map((guild) => <option key={guild.guild_id} value={guild.guild_id}>{guild.name}</option>)}
          </Select>

          {targetKind === 'CHANNEL' && <Select labelKey="campaigns.targets.channel" value={targetChannelId} disabled={!targetGuildId} onChange={(event) => setTargetChannelId(event.target.value)}>
            <option value="">{t('actions.target.choose')}</option>
            {targetChannels.map((channel) => <option key={channel.id} value={channel.id}>{channel.name}</option>)}
          </Select>}

          {targetKind === 'LOGICAL_GROUP' && <Select labelKey="campaigns.targets.logicalGroup" value={targetLogicalGroupId} disabled={!targetGuildId} onChange={(event) => setTargetLogicalGroupId(event.target.value)}>
            <option value="">{t('actions.target.choose')}</option>
            {(targetLogicalGroups.data?.groups ?? []).map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}
          </Select>}

          {targetKind === 'TRANSLATION_GROUP' && <>
            <Select labelKey="campaigns.targets.translationGroup" value={targetTranslationGroupId} disabled={!targetGuildId} onChange={(event) => setTargetTranslationGroupId(event.target.value)}>
              <option value="">{t('actions.target.choose')}</option>
              {targetTranslationGroups.map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}
            </Select>
            <Select labelKey="campaigns.targets.translationMode" value={targetTranslationMode} onChange={(event) => setTargetTranslationMode(event.target.value as TranslationPublicationMode)}>
              {translationPublicationModes.map((mode) => <option key={mode} value={mode}>{t(translationPublicationModeKey(mode))}</option>)}
            </Select>
          </>}
        </div>
        {targetKind === 'TRANSLATION_GROUP' && <p className="hint">{t('campaigns.targets.translationMode.help')}</p>}
        {targetKind === 'TRANSLATION_GROUP' && targetTranslationMode === 'SELECTED_LANGUAGES' && <fieldset className="field">
          <legend>{t('campaigns.targets.selectedLanguages')}</legend>
          <p className="hint">{t('campaigns.targets.selectedLanguages.help')}</p>
          {targetLanguageProfiles.map((language) => <label key={language.id}>
            <input type="checkbox" checked={targetSelectedLanguageIds.includes(language.id)} onChange={() => toggleSelectedLanguage(language.id)} /> {language.display_name}
          </label>)}
        </fieldset>}
        <Button labelKey="campaigns.targets.add" disabled={!targetReady()} onClick={() => void addTarget()} />
      </section>

      <section className="campaign-schedule">
        <h3>{t('campaigns.schedule')}</h3>
        {selected.publication_mode === 'IMMEDIATE' && <p className="hint">{t('campaigns.schedule.immediateNote')}</p>}
        {selected.publication_mode === 'EVENT_TRIGGERED' && <p className="hint">{t('campaigns.schedule.eventNote')}</p>}
        {canCreateSchedule && <div className="schedule-form">
          <Select labelKey="campaigns.schedule.kind" value={scheduleKind} onChange={(event) => setScheduleKind(event.target.value as ScheduleKind)}>
            <option value="ONE_SHOT">{t('campaigns.schedule.oneShot')}</option>
            <option value="RECURRING">{t('campaigns.schedule.recurring')}</option>
          </Select>
          {scheduleKind === 'ONE_SHOT'
            ? <Input labelKey="campaigns.schedule.fireAt" type="datetime-local" value={fireAt} onChange={(event) => setFireAt(event.target.value)} />
            : <><Input labelKey="campaigns.schedule.startsAt" type="datetime-local" value={startsAt} onChange={(event) => setStartsAt(event.target.value)} />
                <Input labelKey="campaigns.schedule.rrule" value={rrule} onChange={(event) => setRrule(event.target.value)} /></>}
          <Input labelKey="campaigns.schedule.timezone" value={timezone} onChange={(event) => setTimezone(event.target.value)} />
          <Button labelKey="campaigns.schedule.create" onClick={() => void createSchedule()} />
          {scheduleResult && <Status>{t('campaigns.schedule.next', { value: scheduleResult.next_fire_at ?? scheduleResult.fire_at ?? '—' })}</Status>}
        </div>}
      </section>

      <section className="campaign-simulate">
        <h3>{t('campaigns.simulate')}</h3>
        <Button labelKey="campaigns.simulate.run" variant="primary" disabled={simulating} onClick={() => void runSimulation()} />
        {simulation ? <div className="simulation-result">
          <p role="status">{t('campaigns.simulate.summary', { ready: simulation.ready_destinations, total: simulation.total_destinations, estimated: simulation.estimated_delivery_count })}</p>
          <ul>{simulation.destinations.map((destination, index) => <li key={index}>
            <Badge tone={destination.ready ? 'ok' : 'danger'}>{t(destination.ready ? 'campaigns.simulate.ready' : 'campaigns.simulate.blocked')}</Badge>
            <Badge tone={destination.delivery_executable ? 'ok' : 'warning'}>{t(destination.delivery_executable ? 'campaigns.simulate.executable' : 'campaigns.simulate.notExecutable')}</Badge>
            <span>{destination.discord_channel_id}</span>
            <span>{t(translationStateKey(destination.translation_state))}</span>
            {destination.blocked_reason && <span>{t(blockedReasonKey(destination.blocked_reason))}</span>}
          </li>)}</ul>
          {Object.keys(simulation.blockers).length > 0 && <div><h4>{t('campaigns.simulate.blockers')}</h4><ul>{Object.entries(simulation.blockers).map(([reason, count]) => <li key={reason}>{t(blockedReasonKey(reason))} ({count})</li>)}</ul></div>}
          {simulation.message_content_warnings.length > 0 && <div><h4>{t('campaigns.simulate.messageContentWarnings')}</h4><ul>{simulation.message_content_warnings.map((warning) => <li key={warning.trigger_id}>
            <Badge tone={warning.is_blocking ? 'danger' : 'ok'}>{t(warning.is_blocking ? 'campaigns.simulate.messageContentBlocked' : 'campaigns.simulate.messageContentAvailable')}</Badge>
          </li>)}</ul></div>}
        </div> : <p>{t('campaigns.simulate.empty')}</p>}
      </section>

      <section className="campaign-lifecycle">
        <h3>{t('campaigns.lifecycle')}</h3>
        <div className="button-row">
          <Button labelKey="campaigns.lifecycle.activate" variant="primary" disabled={!canActivate} disabledReasonKey="actions.disabled.target" onClick={() => void transition('activate')} />
          <Button labelKey="campaigns.lifecycle.pause" disabled={!canPause} disabledReasonKey="actions.disabled.target" onClick={() => void transition('pause')} />
          <Button labelKey="campaigns.lifecycle.resume" disabled={!canResume} disabledReasonKey="actions.disabled.target" onClick={() => void transition('resume')} />
          <Button labelKey="campaigns.lifecycle.cancel" variant="danger" disabled={!canCancel} disabledReasonKey="actions.disabled.target" onClick={() => void transition('cancel')} />
        </div>
      </section>

      <section className="campaign-deliveries">
        <h3>{t('campaigns.deliveries')}</h3>
        {deliveries.isLoading ? <Skeleton /> : (deliveries.data?.deliveries.length ?? 0) === 0 ? <EmptyState messageKey="campaigns.deliveries.empty" /> :
          <table><thead><tr><th>{t('campaigns.deliveries.channel')}</th><th>{t('campaigns.deliveries.status')}</th><th>{t('campaigns.deliveries.attempts')}</th><th>{t('campaigns.deliveries.error')}</th><th>{t('campaigns.deliveries.updated')}</th><th>{t('campaigns.deliveries.actions')}</th></tr></thead>
            <tbody>{deliveries.data?.deliveries.map((delivery) => <tr key={delivery.id}>
              <td>{delivery.discord_channel_id}</td>
              <td><Badge tone={delivery.status === 'SENT' ? 'ok' : delivery.status === 'FAILED' || delivery.status === 'INTERVENTION_REQUIRED' ? 'danger' : 'neutral'}>{t(deliveryStatusKey(delivery.status))}</Badge></td>
              <td>{delivery.attempt_count}</td>
              <td>{delivery.last_error ?? '—'}</td>
              <td>{delivery.updated_at ?? '—'}</td>
              <td>
                {delivery.status === 'INTERVENTION_REQUIRED' && resolvingDeliveryId !== delivery.id &&
                  <Button labelKey="campaigns.deliveries.intervene" onClick={() => { setResolvingDeliveryId(delivery.id); setResolveMessageId('') }} />}
                {delivery.status === 'INTERVENTION_REQUIRED' && resolvingDeliveryId === delivery.id && <div className="intervention-form">
                  <Input labelKey="campaigns.deliveries.messageId" value={resolveMessageId} onChange={(event) => setResolveMessageId(event.target.value)} />
                  <Button labelKey="campaigns.deliveries.resolveSent" variant="primary" disabled={!resolveMessageId} onClick={() => void resolveIntervention(delivery.id, 'SENT')} />
                  <Button labelKey="campaigns.deliveries.resolveFailed" onClick={() => void resolveIntervention(delivery.id, 'FAILED')} />
                  <Button labelKey="common.cancel" onClick={() => setResolvingDeliveryId(null)} />
                </div>}
                {delivery.status === 'FAILED' && <Button labelKey="campaigns.deliveries.requeue" onClick={() => void requeueDelivery(delivery.id)} />}
                {delivery.status === 'SENT' && editingDeliveryId !== delivery.id && <>
                  <Button labelKey="campaigns.deliveries.edit" onClick={() => { setEditingDeliveryId(delivery.id); setDeliveryEditContent('') }} />
                  <Button labelKey="campaigns.deliveries.delete" onClick={() => void deleteDelivery(delivery.id)} />
                </>}
                {delivery.status === 'SENT' && editingDeliveryId === delivery.id && <div className="intervention-form">
                  <label className="field" htmlFor={`delivery-edit-${delivery.id}`}><span>{t('campaigns.deliveries.editContent')}</span><textarea id={`delivery-edit-${delivery.id}`} value={deliveryEditContent} maxLength={2000} onChange={(event) => setDeliveryEditContent(event.target.value)} /></label>
                  <Button labelKey="campaigns.deliveries.saveEdit" variant="primary" disabled={!deliveryEditContent} onClick={() => void editDelivery(delivery.id)} />
                  <Button labelKey="common.cancel" onClick={() => setEditingDeliveryId(null)} />
                </div>}
              </td>
            </tr>)}</tbody></table>}
      </section>

      <section className="campaign-variants">
        <h3>{t('campaigns.variants')}</h3>
        <div className="variant-form">
          <Input labelKey="campaigns.variants.language" value={variantLanguage} minLength={2} maxLength={16} onChange={(event) => setVariantLanguage(event.target.value)} />
          <Button labelKey="campaigns.variants.check" disabled={!variantLanguage} onClick={() => void checkVariant()} />
        </div>
        {variantPreview && <div className="variant-result">
          <p><Badge tone={variantPreview.outcome === 'REUSABLE' ? 'ok' : variantPreview.outcome === 'STALE' ? 'warning' : 'neutral'}>{t(variantOutcomeKey(variantPreview.outcome))}</Badge></p>
          <label className="field" htmlFor="campaign-variant-content"><span>{t('campaigns.variants.content')}</span><textarea id="campaign-variant-content" value={variantContent} maxLength={2000} onChange={(event) => setVariantContent(event.target.value)} /></label>
          <Button labelKey="campaigns.variants.approve" variant="primary" disabled={!variantContent} onClick={() => void approveVariant()} />
        </div>}
      </section>
    </section>}
  </section>
}
