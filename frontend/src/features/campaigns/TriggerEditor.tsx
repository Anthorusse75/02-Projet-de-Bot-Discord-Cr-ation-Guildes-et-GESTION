import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { apiRequest, ApiError } from '../../api/client'
import { useCampaignTriggers, useTriggerSources } from '../../api/queries'
import type { DiscordSnowflake } from '../../shared/discord-id'
import type { CampaignTrigger, TriggerSourceScopeKind } from '../../api/types'
import type { MessageKey } from '../../localization/catalog'
import { campaignErrorKey, triggerConditionOpKey, triggerSourceScopeKindKey } from '../../localization/presentation'
import { Badge, Button, EmptyState, Input, Select, Skeleton } from '../../shared/components/ui'

type ComparisonOp = 'EQUALS' | 'NOT_EQUALS' | 'CONTAINS'
type ValueType = 'STRING' | 'NUMBER' | 'BOOLEAN'
type ConditionKind = 'ALWAYS' | 'COMPARISON' | 'ALL_OF' | 'ANY_OF'
type ClauseRow = { op: ComparisonOp; path: string; value: string; valueType: ValueType }

const comparisonOps: readonly ComparisonOp[] = ['EQUALS', 'NOT_EQUALS', 'CONTAINS']
const valueTypes: readonly ValueType[] = ['STRING', 'NUMBER', 'BOOLEAN']
const conditionKinds: readonly ConditionKind[] = ['ALWAYS', 'COMPARISON', 'ALL_OF', 'ANY_OF']
const sourceScopeKinds: readonly TriggerSourceScopeKind[] = ['GUILD', 'CHANNEL', 'CATEGORY']

function newClause(): ClauseRow {
  return { op: 'EQUALS', path: '', value: '', valueType: 'STRING' }
}

function parseTypedValue(raw: string, valueType: ValueType): string | number | boolean {
  if (valueType === 'NUMBER') return Number(raw)
  if (valueType === 'BOOLEAN') return raw === 'true'
  return raw
}

function errorKey(error: unknown): MessageKey {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'errors.auth.required'
    if (error.status === 403) return 'errors.authorization.denied'
    return campaignErrorKey(error.problem.code)
  }
  return 'errors.generic'
}

/** REQ-MSG-027/030 mission section 12: an event trigger's condition is
 * always authored through this structured, allowlisted builder --
 * ALWAYS / a single comparison / an ALL_OF (AND) or ANY_OF (OR) list of
 * comparisons -- and serialized to the exact AST shape
 * did.campaigns.causality.validate_condition_ast accepts. There is no raw
 * expression/code field anywhere in this component; the backend's allowlist
 * (did.domain.campaigns.TriggerConditionOp) is the only source of truth for
 * what an author can express. */
export function TriggerEditor({ campaignId, userId }: { campaignId: string; userId: DiscordSnowflake }) {
  const { t } = useTranslation()
  const triggers = useCampaignTriggers(userId, campaignId)
  const [problemKey, setProblemKey] = useState<MessageKey | null>(null)
  const [feedbackKey, setFeedbackKey] = useState<MessageKey | null>(null)

  const [eventType, setEventType] = useState('')
  const [maxCausationDepth, setMaxCausationDepth] = useState(8)
  const [requiresMessageContent, setRequiresMessageContent] = useState(false)
  const [conditionKind, setConditionKind] = useState<ConditionKind>('ALWAYS')
  const [comparison, setComparison] = useState<ClauseRow>(newClause())
  const [clauses, setClauses] = useState<ClauseRow[]>([])

  const [selectedTriggerId, setSelectedTriggerId] = useState<string | null>(null)
  const [sourceGuildId, setSourceGuildId] = useState('')
  const sources = useTriggerSources(userId, campaignId, selectedTriggerId ?? undefined, sourceGuildId)
  const [sourceScopeKind, setSourceScopeKind] = useState<TriggerSourceScopeKind>('CHANNEL')
  const [sourceResourceId, setSourceResourceId] = useState('')

  function resetTriggerForm() {
    setEventType(''); setMaxCausationDepth(8); setRequiresMessageContent(false)
    setConditionKind('ALWAYS'); setComparison(newClause()); setClauses([])
  }

  function buildConditionAst(): Record<string, unknown> {
    if (conditionKind === 'ALWAYS') return { op: 'ALWAYS' }
    if (conditionKind === 'COMPARISON') {
      return { op: comparison.op, path: comparison.path, value: parseTypedValue(comparison.value, comparison.valueType) }
    }
    return {
      op: conditionKind === 'ALL_OF' ? 'AND' : 'OR',
      clauses: clauses.map((clause) => ({ op: clause.op, path: clause.path, value: parseTypedValue(clause.value, clause.valueType) })),
    }
  }

  function describeConditionAst(ast: Record<string, unknown>): string {
    const op = String(ast.op)
    if (op === 'ALWAYS') return t(triggerConditionOpKey(op))
    if (op === 'AND' || op === 'OR') {
      const nested = Array.isArray(ast.clauses) ? (ast.clauses as Record<string, unknown>[]) : []
      return nested.map((clause) => describeConditionAst(clause)).join(` ${t(triggerConditionOpKey(op))} `)
    }
    return `${String(ast.path)} ${t(triggerConditionOpKey(op))} ${JSON.stringify(ast.value)}`
  }

  const createTriggerReady = Boolean(eventType)
    && (conditionKind !== 'COMPARISON' || Boolean(comparison.path))
    && (!(conditionKind === 'ALL_OF' || conditionKind === 'ANY_OF') || clauses.length > 0)

  async function createTrigger() {
    setProblemKey(null)
    try {
      await apiRequest(`/api/v1/campaigns/${campaignId}/triggers`, {
        method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() },
        body: {
          event_type: eventType, condition_ast: buildConditionAst(),
          max_causation_depth: maxCausationDepth, requires_message_content: requiresMessageContent,
        },
      })
      setFeedbackKey('campaigns.triggers.created')
      resetTriggerForm()
      await triggers.refetch()
    } catch (error) { setProblemKey(errorKey(error)) }
  }

  async function createSource() {
    setProblemKey(null)
    if (!selectedTriggerId) return
    try {
      await apiRequest(`/api/v1/campaigns/${campaignId}/triggers/${selectedTriggerId}/sources`, {
        method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() },
        body: {
          guild_id: sourceGuildId, source_scope_kind: sourceScopeKind,
          discord_resource_id: sourceScopeKind === 'GUILD' ? null : sourceResourceId,
        },
      })
      setFeedbackKey('campaigns.triggers.sourceCreated')
      setSourceResourceId('')
      await sources.refetch()
    } catch (error) { setProblemKey(errorKey(error)) }
  }

  const createSourceReady = Boolean(sourceGuildId) && (sourceScopeKind === 'GUILD' || Boolean(sourceResourceId))

  return <section className="campaign-triggers">
    <h3>{t('campaigns.triggers')}</h3>
    {problemKey && <p role="alert">{t(problemKey, { requestId: 'unknown' })}</p>}
    {feedbackKey && <p role="status">{t(feedbackKey)}</p>}

    {triggers.isLoading ? <Skeleton /> : (triggers.data?.triggers.length ?? 0) === 0 ? <EmptyState messageKey="campaigns.triggers.empty" /> :
      <ul>{triggers.data?.triggers.map((trigger: CampaignTrigger) => <li key={trigger.id} className="trigger-row">
        <strong>{trigger.event_type}</strong>
        <Badge>{describeConditionAst(trigger.condition_ast)}</Badge>
        <Badge>{t('campaigns.triggers.causationDepth', { value: trigger.max_causation_depth })}</Badge>
        {trigger.requires_message_content && <Badge tone="warning">{t('campaigns.triggers.requiresMessageContent')}</Badge>}
        <Button labelKey="campaigns.triggers.manageSources" onClick={() => { setSelectedTriggerId(trigger.id); setSourceGuildId('') }} />
      </li>)}</ul>}

    <div className="trigger-form">
      <Input labelKey="campaigns.triggers.eventType" id="trigger-create-event-type" value={eventType} maxLength={128} onChange={(event) => setEventType(event.target.value)} />
      <Select labelKey="campaigns.triggers.conditionKind" id="trigger-create-condition-kind" value={conditionKind} onChange={(event) => setConditionKind(event.target.value as ConditionKind)}>
        {conditionKinds.map((kind) => <option key={kind} value={kind}>{t(`campaigns.triggers.conditionKind.${kind === 'ALWAYS' ? 'always' : kind === 'COMPARISON' ? 'comparison' : kind === 'ALL_OF' ? 'allOf' : 'anyOf'}` as MessageKey)}</option>)}
      </Select>

      {conditionKind === 'COMPARISON' && <div className="trigger-condition-clause">
        <Select labelKey="campaigns.triggers.op" id="trigger-comparison-op" value={comparison.op} onChange={(event) => setComparison((current) => ({ ...current, op: event.target.value as ComparisonOp }))}>
          {comparisonOps.map((op) => <option key={op} value={op}>{t(triggerConditionOpKey(op))}</option>)}
        </Select>
        <Input labelKey="campaigns.triggers.path" id="trigger-comparison-path" value={comparison.path} onChange={(event) => setComparison((current) => ({ ...current, path: event.target.value }))} />
        <Select labelKey="campaigns.triggers.valueType" id="trigger-comparison-value-type" value={comparison.valueType} onChange={(event) => setComparison((current) => ({ ...current, valueType: event.target.value as ValueType }))}>
          {valueTypes.map((type) => <option key={type} value={type}>{t(`campaigns.triggers.valueType.${type.toLowerCase()}` as MessageKey)}</option>)}
        </Select>
        <Input labelKey="campaigns.triggers.value" id="trigger-comparison-value" value={comparison.value} onChange={(event) => setComparison((current) => ({ ...current, value: event.target.value }))} />
      </div>}

      {(conditionKind === 'ALL_OF' || conditionKind === 'ANY_OF') && <div className="trigger-condition-clauses">
        {clauses.map((clause, index) => <div key={index} className="trigger-condition-clause">
          <Select labelKey="campaigns.triggers.op" id={`trigger-clause-${index}-op`} value={clause.op} onChange={(event) => setClauses((current) => current.map((row, rowIndex) => rowIndex === index ? { ...row, op: event.target.value as ComparisonOp } : row))}>
            {comparisonOps.map((op) => <option key={op} value={op}>{t(triggerConditionOpKey(op))}</option>)}
          </Select>
          <Input labelKey="campaigns.triggers.path" id={`trigger-clause-${index}-path`} value={clause.path} onChange={(event) => setClauses((current) => current.map((row, rowIndex) => rowIndex === index ? { ...row, path: event.target.value } : row))} />
          <Select labelKey="campaigns.triggers.valueType" id={`trigger-clause-${index}-value-type`} value={clause.valueType} onChange={(event) => setClauses((current) => current.map((row, rowIndex) => rowIndex === index ? { ...row, valueType: event.target.value as ValueType } : row))}>
            {valueTypes.map((type) => <option key={type} value={type}>{t(`campaigns.triggers.valueType.${type.toLowerCase()}` as MessageKey)}</option>)}
          </Select>
          <Input labelKey="campaigns.triggers.value" id={`trigger-clause-${index}-value`} value={clause.value} onChange={(event) => setClauses((current) => current.map((row, rowIndex) => rowIndex === index ? { ...row, value: event.target.value } : row))} />
          <Button type="button" labelKey="campaigns.triggers.removeClause" onClick={() => setClauses((current) => current.filter((_, rowIndex) => rowIndex !== index))} />
        </div>)}
        <Button type="button" labelKey="campaigns.triggers.addClause" onClick={() => setClauses((current) => [...current, newClause()])} />
      </div>}

      <Input labelKey="campaigns.triggers.maxCausationDepth" id="trigger-create-depth" type="number" value={String(maxCausationDepth)} onChange={(event) => setMaxCausationDepth(Number(event.target.value))} />
      <label><input type="checkbox" checked={requiresMessageContent} onChange={(event) => setRequiresMessageContent(event.target.checked)} /> {t('campaigns.triggers.requiresMessageContent')}</label>
      {requiresMessageContent && <p className="hint">{t('campaigns.triggers.requiresMessageContentWarning')}</p>}
      <Button type="button" labelKey="campaigns.triggers.add" variant="primary" disabled={!createTriggerReady} onClick={() => void createTrigger()} />
    </div>

    {selectedTriggerId && <div className="trigger-sources">
      <h4>{t('campaigns.triggers.sources')}</h4>
      <Input labelKey="campaigns.triggers.sourceGuildId" id="trigger-source-guild-id" value={sourceGuildId} onChange={(event) => setSourceGuildId(event.target.value)} />
      {!sourceGuildId ? <p className="hint">{t('campaigns.glossary.load')}</p> :
        sources.isLoading ? <Skeleton /> : (sources.data?.trigger_sources.length ?? 0) === 0 ? <EmptyState messageKey="campaigns.triggers.sourcesEmpty" /> :
        <ul>{sources.data?.trigger_sources.map((source) => <li key={source.id} className="trigger-source-row">
          <Badge>{t(triggerSourceScopeKindKey(source.source_scope_kind))}</Badge>
          {source.discord_resource_id && <span>{source.discord_resource_id}</span>}
        </li>)}</ul>}
      <div className="trigger-source-form">
        <Select labelKey="campaigns.triggers.sourceScope" id="trigger-source-scope" value={sourceScopeKind} onChange={(event) => setSourceScopeKind(event.target.value as TriggerSourceScopeKind)}>
          {sourceScopeKinds.map((kind) => <option key={kind} value={kind}>{t(triggerSourceScopeKindKey(kind))}</option>)}
        </Select>
        {sourceScopeKind !== 'GUILD' && <Input labelKey="campaigns.triggers.sourceResourceId" id="trigger-source-resource-id" value={sourceResourceId} onChange={(event) => setSourceResourceId(event.target.value)} />}
        <Button type="button" labelKey="campaigns.triggers.addSource" variant="primary" disabled={!createSourceReady} onClick={() => void createSource()} />
      </div>
    </div>}
  </section>
}
