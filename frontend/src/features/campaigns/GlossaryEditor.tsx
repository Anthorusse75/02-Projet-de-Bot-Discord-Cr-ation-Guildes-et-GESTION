import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { apiRequest, ApiError } from '../../api/client'
import { useCampaignGlossary, useGlobalUserGlossary, useGuildGlossary } from '../../api/queries'
import type { DiscordSnowflake } from '../../shared/discord-id'
import type { GlossaryBehavior, GlossaryEntry, GlossaryMatchMode, GlossaryScope } from '../../api/types'
import type { MessageKey } from '../../localization/catalog'
import { campaignErrorKey, glossaryBehaviorKey, glossaryMatchModeKey, glossaryScopeKey } from '../../localization/presentation'
import { Badge, Button, EmptyState, Input, Select, Skeleton } from '../../shared/components/ui'

const glossaryScopes: readonly GlossaryScope[] = ['CAMPAIGN', 'GUILD', 'GLOBAL_USER']
const glossaryBehaviors: readonly GlossaryBehavior[] = ['DO_NOT_TRANSLATE', 'FORCED_TRANSLATION']
const glossaryMatchModes: readonly GlossaryMatchMode[] = ['CASE_INSENSITIVE', 'EXACT']

function errorKey(error: unknown): MessageKey {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'errors.auth.required'
    if (error.status === 403) return 'errors.authorization.denied'
    return campaignErrorKey(error.problem.code)
  }
  return 'errors.generic'
}

/** REQ-MSG-014 mission section 11: typed glossary authoring across the
 * three canonical scopes (CAMPAIGN/GUILD/GLOBAL_USER). Priority and
 * matching semantics live entirely in the backend
 * (did.campaigns.glossary.resolve_applicable_entries); this editor only
 * authors entries, it never re-implements the specificity ordering. */
export function GlossaryEditor({ campaignId, userId }: { campaignId: string; userId: DiscordSnowflake }) {
  const { t } = useTranslation()
  const [scope, setScope] = useState<GlossaryScope>('CAMPAIGN')
  const [guildId, setGuildId] = useState('')

  const campaignEntries = useCampaignGlossary(userId, campaignId)
  const globalEntries = useGlobalUserGlossary(userId)
  const guildEntries = useGuildGlossary(userId, guildId)

  const activeQuery = scope === 'CAMPAIGN' ? campaignEntries : scope === 'GLOBAL_USER' ? globalEntries : guildEntries
  const entries: GlossaryEntry[] = activeQuery.data?.glossary_entries ?? []

  const [problemKey, setProblemKey] = useState<MessageKey | null>(null)
  const [feedbackKey, setFeedbackKey] = useState<MessageKey | null>(null)

  const [sourceTerm, setSourceTerm] = useState('')
  const [behavior, setBehavior] = useState<GlossaryBehavior>('DO_NOT_TRANSLATE')
  const [matchMode, setMatchMode] = useState<GlossaryMatchMode>('CASE_INSENSITIVE')
  const [targetLanguageCode, setTargetLanguageCode] = useState('')
  const [forcedTranslation, setForcedTranslation] = useState('')

  function resetForm() {
    setSourceTerm(''); setBehavior('DO_NOT_TRANSLATE'); setMatchMode('CASE_INSENSITIVE')
    setTargetLanguageCode(''); setForcedTranslation('')
  }

  async function refetchActive() {
    if (scope === 'CAMPAIGN') await campaignEntries.refetch()
    else if (scope === 'GLOBAL_USER') await globalEntries.refetch()
    else await guildEntries.refetch()
  }

  async function createEntry() {
    setProblemKey(null)
    try {
      const body: Record<string, unknown> = {
        scope_kind: scope,
        source_term: sourceTerm,
        behavior,
        match_mode: matchMode,
        target_language_code: targetLanguageCode.trim() || null,
        forced_translation: behavior === 'FORCED_TRANSLATION' ? forcedTranslation : null,
        campaign_id: scope === 'CAMPAIGN' ? campaignId : null,
        guild_id: scope === 'GUILD' ? guildId : null,
      }
      await apiRequest('/api/v1/glossary', { method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() }, body })
      setFeedbackKey('campaigns.glossary.created')
      resetForm()
      await refetchActive()
    } catch (error) { setProblemKey(errorKey(error)) }
  }

  async function deleteEntry(entryId: string) {
    setProblemKey(null)
    try {
      await apiRequest(`/api/v1/glossary/${entryId}`, { method: 'DELETE' })
      setFeedbackKey('campaigns.glossary.deleted')
      await refetchActive()
    } catch (error) { setProblemKey(errorKey(error)) }
  }

  const createReady = Boolean(sourceTerm)
    && (scope !== 'GUILD' || Boolean(guildId))
    && (behavior !== 'FORCED_TRANSLATION' || Boolean(forcedTranslation))

  return <section className="campaign-glossary">
    <h3>{t('campaigns.glossary')}</h3>
    {problemKey && <p role="alert">{t(problemKey, { requestId: 'unknown' })}</p>}
    {feedbackKey && <p role="status">{t(feedbackKey)}</p>}

    <Select labelKey="campaigns.glossary.scope" id="glossary-scope" value={scope} onChange={(event) => setScope(event.target.value as GlossaryScope)}>
      {glossaryScopes.map((value) => <option key={value} value={value}>{t(glossaryScopeKey(value))}</option>)}
    </Select>
    {scope === 'GUILD' && <Input labelKey="campaigns.glossary.guildId" id="glossary-guild-id" value={guildId} onChange={(event) => setGuildId(event.target.value)} />}

    {scope === 'GUILD' && !guildId ? <p className="hint">{t('campaigns.glossary.load')}</p> :
      activeQuery.isLoading ? <Skeleton /> : entries.length === 0 ? <EmptyState messageKey="campaigns.glossary.empty" /> :
      <ul>{entries.map((entry) => <li key={entry.id} className="glossary-entry-row">
        <strong>{entry.source_term}</strong>
        <Badge>{t(glossaryBehaviorKey(entry.behavior))}</Badge>
        <Badge>{t(glossaryMatchModeKey(entry.match_mode))}</Badge>
        {entry.target_language_code && <Badge>{entry.target_language_code}</Badge>}
        {entry.behavior === 'FORCED_TRANSLATION' && <span>{entry.forced_translation}</span>}
        <Button labelKey="campaigns.glossary.delete" onClick={() => void deleteEntry(entry.id)} />
      </li>)}</ul>}

    <div className="glossary-form">
      <Input labelKey="campaigns.glossary.sourceTerm" id="glossary-create-term" value={sourceTerm} maxLength={200} onChange={(event) => setSourceTerm(event.target.value)} />
      <Select labelKey="campaigns.glossary.behavior" id="glossary-create-behavior" value={behavior} onChange={(event) => setBehavior(event.target.value as GlossaryBehavior)}>
        {glossaryBehaviors.map((value) => <option key={value} value={value}>{t(glossaryBehaviorKey(value))}</option>)}
      </Select>
      {behavior === 'FORCED_TRANSLATION' && <Input labelKey="campaigns.glossary.forcedTranslation" id="glossary-create-forced" value={forcedTranslation} maxLength={2000} onChange={(event) => setForcedTranslation(event.target.value)} />}
      <Select labelKey="campaigns.glossary.matchMode" id="glossary-create-matchmode" value={matchMode} onChange={(event) => setMatchMode(event.target.value as GlossaryMatchMode)}>
        {glossaryMatchModes.map((value) => <option key={value} value={value}>{t(glossaryMatchModeKey(value))}</option>)}
      </Select>
      <Input labelKey="campaigns.glossary.targetLanguageCode" id="glossary-create-language" value={targetLanguageCode} maxLength={16} onChange={(event) => setTargetLanguageCode(event.target.value)} />
      <Button type="button" labelKey="campaigns.glossary.add" variant="primary" disabled={!createReady} onClick={() => void createEntry()} />
    </div>
  </section>
}
