import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { apiRequest, ApiError } from '../../api/client'
import { useCampaignTemplateVariables } from '../../api/queries'
import type { DiscordSnowflake } from '../../shared/discord-id'
import type { TemplateVariable, TemplateVariableType } from '../../api/types'
import type { MessageKey } from '../../localization/catalog'
import { campaignErrorKey, templateVariableTypeKey } from '../../localization/presentation'
import { Badge, Button, EmptyState, Input, Select, Skeleton } from '../../shared/components/ui'

const templateVariableTypes: readonly TemplateVariableType[] = ['TRANSLATABLE_TEXT', 'NON_TRANSLATABLE', 'LOCALIZED_VALUE', 'PROTECTED']

function errorKey(error: unknown): MessageKey {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'errors.auth.required'
    if (error.status === 403) return 'errors.authorization.denied'
    return campaignErrorKey(error.problem.code)
  }
  return 'errors.generic'
}

/** REQ-MSG-018 mission section 10: typed template-variable authoring
 * against the real backend schema (did.messaging.template_variables) --
 * TRANSLATABLE_TEXT/NON_TRANSLATABLE/PROTECTED carry a single value,
 * LOCALIZED_VALUE carries one value per target language, chosen by the
 * author here rather than guessed. */
export function TemplateVariableEditor({ campaignId, userId }: { campaignId: string; userId: DiscordSnowflake }) {
  const { t } = useTranslation()
  const variables = useCampaignTemplateVariables(userId, campaignId)
  const [problemKey, setProblemKey] = useState<MessageKey | null>(null)
  const [feedbackKey, setFeedbackKey] = useState<MessageKey | null>(null)

  const [name, setName] = useState('')
  const [variableType, setVariableType] = useState<TemplateVariableType>('TRANSLATABLE_TEXT')
  const [value, setValue] = useState('')
  const [languageCode, setLanguageCode] = useState('')
  const [languageValues, setLanguageValues] = useState<Record<string, string>>({})

  const [editingId, setEditingId] = useState<string | null>(null)
  const [editVariableType, setEditVariableType] = useState<TemplateVariableType>('TRANSLATABLE_TEXT')
  const [editValue, setEditValue] = useState('')
  const [editLanguageValues, setEditLanguageValues] = useState<Record<string, string>>({})

  function resetCreateForm() {
    setName(''); setVariableType('TRANSLATABLE_TEXT'); setValue(''); setLanguageCode(''); setLanguageValues({})
  }

  function addLanguageValue() {
    if (!languageCode.trim()) return
    setLanguageValues((current) => ({ ...current, [languageCode.trim()]: value }))
    setLanguageCode(''); setValue('')
  }

  function removeLanguageValue(code: string) {
    setLanguageValues((current) => Object.fromEntries(Object.entries(current).filter(([key]) => key !== code)))
  }

  async function createVariable() {
    setProblemKey(null)
    try {
      const body: Record<string, unknown> = { name, variable_type: variableType }
      if (variableType === 'LOCALIZED_VALUE') body.values_by_language = languageValues
      else body.value = value
      await apiRequest(`/api/v1/campaigns/${campaignId}/template-variables`, {
        method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() }, body,
      })
      setFeedbackKey('campaigns.templateVariables.created')
      resetCreateForm()
      await variables.refetch()
    } catch (error) { setProblemKey(errorKey(error)) }
  }

  function startEdit(variable: TemplateVariable) {
    setEditingId(variable.id)
    setEditVariableType(variable.variable_type)
    setEditValue(variable.value ?? '')
    setEditLanguageValues(variable.values_by_language ?? {})
  }

  async function saveEdit(variableId: string) {
    setProblemKey(null)
    try {
      const body: Record<string, unknown> = { variable_type: editVariableType }
      if (editVariableType === 'LOCALIZED_VALUE') body.values_by_language = editLanguageValues
      else body.value = editValue
      await apiRequest(`/api/v1/campaigns/${campaignId}/template-variables/${variableId}`, {
        method: 'PATCH', body,
      })
      setFeedbackKey('campaigns.templateVariables.updated')
      setEditingId(null)
      await variables.refetch()
    } catch (error) { setProblemKey(errorKey(error)) }
  }

  async function deleteVariable(variableId: string) {
    setProblemKey(null)
    try {
      await apiRequest(`/api/v1/campaigns/${campaignId}/template-variables/${variableId}`, { method: 'DELETE' })
      setFeedbackKey('campaigns.templateVariables.deleted')
      await variables.refetch()
    } catch (error) { setProblemKey(errorKey(error)) }
  }

  const createReady = variableType === 'LOCALIZED_VALUE' ? Boolean(name) && Object.keys(languageValues).length > 0 : Boolean(name) && Boolean(value)

  return <section className="campaign-template-variables">
    <h3>{t('campaigns.templateVariables')}</h3>
    {problemKey && <p role="alert">{t(problemKey, { requestId: 'unknown' })}</p>}
    {feedbackKey && <p role="status">{t(feedbackKey)}</p>}
    {variables.isLoading ? <Skeleton /> : (variables.data?.template_variables.length ?? 0) === 0 ? <EmptyState messageKey="campaigns.templateVariables.empty" /> :
      <ul>{variables.data?.template_variables.map((variable) => <li key={variable.id} className="template-variable-row">
        {editingId === variable.id ? <div className="intervention-form">
          <strong>{`{{${variable.name}}}`}</strong>
          <Select labelKey="campaigns.templateVariables.type" id={`tv-edit-${variable.id}-type`} value={editVariableType} onChange={(event) => setEditVariableType(event.target.value as TemplateVariableType)}>
            {templateVariableTypes.map((type) => <option key={type} value={type}>{t(templateVariableTypeKey(type))}</option>)}
          </Select>
          {editVariableType === 'LOCALIZED_VALUE' ? <>
            {Object.entries(editLanguageValues).map(([code, localizedValue]) => <Badge key={code}>{code}: {localizedValue}</Badge>)}
            <Input labelKey="campaigns.templateVariables.languageCode" id={`tv-edit-${variable.id}-lang`} value={languageCode} maxLength={16} onChange={(event) => setLanguageCode(event.target.value)} />
            <Input labelKey="campaigns.templateVariables.value" id={`tv-edit-${variable.id}-langvalue`} value={value} onChange={(event) => setValue(event.target.value)} />
            <Button type="button" labelKey="campaigns.templateVariables.addLanguageValue" onClick={() => { if (languageCode.trim()) { setEditLanguageValues((current) => ({ ...current, [languageCode.trim()]: value })); setLanguageCode(''); setValue('') } }} />
          </> : <Input labelKey="campaigns.templateVariables.value" id={`tv-edit-${variable.id}-value`} value={editValue} onChange={(event) => setEditValue(event.target.value)} />}
          <Button labelKey="common.confirm" variant="primary" onClick={() => void saveEdit(variable.id)} />
          <Button labelKey="common.cancel" onClick={() => setEditingId(null)} />
        </div> : <>
          <strong>{`{{${variable.name}}}`}</strong>
          <Badge>{t(templateVariableTypeKey(variable.variable_type))}</Badge>
          {variable.variable_type === 'LOCALIZED_VALUE'
            ? <span>{Object.entries(variable.values_by_language ?? {}).map(([code, localizedValue]) => `${code}: ${localizedValue}`).join(', ')}</span>
            : <span>{variable.value}</span>}
          <Button labelKey="campaigns.templateVariables.edit" onClick={() => startEdit(variable)} />
          <Button labelKey="campaigns.templateVariables.delete" onClick={() => void deleteVariable(variable.id)} />
        </>}
      </li>)}</ul>}

    <div className="template-variable-form">
      <Input labelKey="campaigns.templateVariables.name" id="tv-create-name" value={name} maxLength={128} onChange={(event) => setName(event.target.value)} />
      <Select labelKey="campaigns.templateVariables.type" id="tv-create-type" value={variableType} onChange={(event) => { setVariableType(event.target.value as TemplateVariableType); setValue(''); setLanguageValues({}) }}>
        {templateVariableTypes.map((type) => <option key={type} value={type}>{t(templateVariableTypeKey(type))}</option>)}
      </Select>
      {variableType === 'LOCALIZED_VALUE' ? <>
        {Object.entries(languageValues).map(([code, localizedValue]) => <Badge key={code}>{code}: {localizedValue} <button type="button" onClick={() => removeLanguageValue(code)}>×</button></Badge>)}
        <Input labelKey="campaigns.templateVariables.languageCode" id="tv-create-lang" value={languageCode} maxLength={16} onChange={(event) => setLanguageCode(event.target.value)} />
        <Input labelKey="campaigns.templateVariables.value" id="tv-create-langvalue" value={value} onChange={(event) => setValue(event.target.value)} />
        <Button type="button" labelKey="campaigns.templateVariables.addLanguageValue" onClick={addLanguageValue} />
      </> : <Input labelKey="campaigns.templateVariables.value" id="tv-create-value" value={value} onChange={(event) => setValue(event.target.value)} />}
      <Button type="button" labelKey="campaigns.templateVariables.add" variant="primary" disabled={!createReady} onClick={() => void createVariable()} />
    </div>
  </section>
}
