import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useOutletContext } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ApiError, apiRequest } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import { useCampaignDeliveries, useCampaignTargets, useCampaigns } from '../../api/queries'
import type { Campaign, CampaignSchedule, CampaignSimulationReport, CampaignVariantPreview, PublicationMode, ScheduleKind, Structure } from '../../api/types'
import type { DashboardContext } from '../../app/AppShell'
import type { MessageKey } from '../../localization/catalog'
import { attachmentPolicyKey, blockedReasonKey, campaignErrorKey, campaignStatusKey, deliveryStatusKey, publicationModeKey, targetKindKey, translationStateKey, variantOutcomeKey } from '../../localization/presentation'
import { Badge, Button, EmptyState, ErrorState, Input, Select, Skeleton, Status, Toast } from '../../shared/components/ui'
import './campaigns.css'

const publicationModes: readonly PublicationMode[] = ['IMMEDIATE', 'ONE_SHOT_DEFERRED', 'RECURRING', 'EVENT_TRIGGERED']
const scheduledModes: readonly PublicationMode[] = ['ONE_SHOT_DEFERRED', 'RECURRING']

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
  const [publicationMode, setPublicationMode] = useState<PublicationMode>('IMMEDIATE')
  const [problemKey, setProblemKey] = useState<MessageKey | null>(null)
  const [feedbackKey, setFeedbackKey] = useState<MessageKey | null>(null)

  const [editContent, setEditContent] = useState('')
  const [editAllowEveryone, setEditAllowEveryone] = useState(false)

  const [targetGuildId, setTargetGuildId] = useState('')
  const [targetChannelId, setTargetChannelId] = useState('')
  const targets = useCampaignTargets(userId, selected?.id)
  // A target may be created for any Guild the caller is authorized in, not
  // only the Guild currently active in the shell -- so this queries the
  // real per-Guild channel structure for whichever destination Guild is
  // picked in the "add target" form, never a fake/static channel list.
  const targetStructure = useQuery({
    enabled: Boolean(targetGuildId),
    queryKey: ['did', userId, targetGuildId || 'none', 'campaign-target-structure'],
    queryFn: () => apiRequest<Structure>(`/api/v1/guilds/${targetGuildId}/structure`),
  })
  const targetChannels = targetStructure.data
    ? [...targetStructure.data.root_channels, ...targetStructure.data.categories.flatMap((category) => category.channels)]
    : []

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

  useEffect(() => {
    if (!selected) return
    setEditContent(selected.message_model.content)
    setEditAllowEveryone(Boolean(selected.allowed_mentions_policy.allow_everyone))
  }, [selectedId])

  function selectCampaign(id: string) {
    setSelectedId(id); setProblemKey(null); setFeedbackKey(null)
    setSimulation(null); setScheduleResult(null); setVariantPreview(null); setVariantLanguage(''); setVariantContent('')
    setTargetGuildId(''); setTargetChannelId('')
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
        body: { name, source_language_code: sourceLanguage, message_model: { content: messageContent, embeds: [] }, allowed_mentions_policy: {}, publication_mode: publicationMode },
      })
      setFeedbackKey('campaigns.created')
      setName(''); setMessageContent('')
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
        body: { expected_version: selected.version, message_model: { content: editContent, embeds: [] }, allowed_mentions_policy: { allow_everyone: editAllowEveryone } },
      })
      replaceCampaign(response)
      setFeedbackKey('campaigns.detail.saved')
    } catch (error) { setProblemKey(errorKey(error)) }
  }

  async function addTarget() {
    if (!selected || !targetGuildId || !targetChannelId) return
    setProblemKey(null)
    try {
      await apiRequest(`/api/v1/campaigns/${selected.id}/targets`, {
        method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() },
        body: { guild_id: targetGuildId, target_kind: 'CHANNEL', discord_channel_id: targetChannelId },
      })
      setFeedbackKey('campaigns.targets.added')
      setTargetChannelId('')
      await targets.refetch()
    } catch (error) { setProblemKey(errorKey(error)) }
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
      <fieldset className="field"><legend>{t('campaigns.mentions')}</legend>
        <label><input type="checkbox" checked={!editAllowEveryone} onChange={() => setEditAllowEveryone(false)} /> {t('campaigns.mentions.none')}</label>
        <label><input type="checkbox" checked={editAllowEveryone} onChange={() => setEditAllowEveryone(true)} /> {t('campaigns.mentions.everyone')}</label>
      </fieldset>
      <Button labelKey="campaigns.detail.save" variant="primary" onClick={() => void saveDetail()} />

      <section className="campaign-targets">
        <h3>{t('campaigns.targets')}</h3>
        <p className="hint">{t('campaigns.targets.deferredNote')}</p>
        {targets.isLoading ? <Skeleton /> : (targets.data?.targets.length ?? 0) === 0 ? <EmptyState messageKey="campaigns.targets.empty" /> :
          <ul>{targets.data?.targets.map((target) => <li key={target.id}><Badge>{t(targetKindKey(target.target_kind))}</Badge> {target.guild_id} / {target.discord_channel_id ?? '—'}</li>)}</ul>}
        <div className="target-form">
          <Select labelKey="campaigns.targets.guild" value={targetGuildId} onChange={(event) => { setTargetGuildId(event.target.value); setTargetChannelId('') }}>
            <option value="">{t('actions.target.choose')}</option>
            {guilds.map((guild) => <option key={guild.guild_id} value={guild.guild_id}>{guild.name}</option>)}
          </Select>
          <Select labelKey="campaigns.targets.channel" value={targetChannelId} disabled={!targetGuildId} onChange={(event) => setTargetChannelId(event.target.value)}>
            <option value="">{t('actions.target.choose')}</option>
            {targetChannels.map((channel) => <option key={channel.id} value={channel.id}>{channel.name}</option>)}
          </Select>
          <Button labelKey="campaigns.targets.add" disabled={!targetGuildId || !targetChannelId} onClick={() => void addTarget()} />
        </div>
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
          {simulation.blockers.length > 0 && <div><h4>{t('campaigns.simulate.blockers')}</h4><ul>{simulation.blockers.map((blocker, index) => <li key={index}>{blocker}</li>)}</ul></div>}
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
          <table><thead><tr><th>{t('campaigns.deliveries.channel')}</th><th>{t('campaigns.deliveries.status')}</th><th>{t('campaigns.deliveries.attempts')}</th><th>{t('campaigns.deliveries.error')}</th><th>{t('campaigns.deliveries.updated')}</th></tr></thead>
            <tbody>{deliveries.data?.deliveries.map((delivery) => <tr key={delivery.id}>
              <td>{delivery.discord_channel_id}</td>
              <td><Badge tone={delivery.status === 'SENT' ? 'ok' : delivery.status === 'FAILED' || delivery.status === 'INTERVENTION_REQUIRED' ? 'danger' : 'neutral'}>{t(deliveryStatusKey(delivery.status))}</Badge></td>
              <td>{delivery.attempt_count}</td>
              <td>{delivery.last_error ?? '—'}</td>
              <td>{delivery.updated_at ?? '—'}</td>
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
