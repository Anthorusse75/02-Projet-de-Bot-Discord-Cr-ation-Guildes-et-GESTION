import { useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { apiRequest } from '../../api/client'
import type { DashboardContext } from '../../app/AppShell'
import { Badge, Button, Input, Select } from '../../shared/components/ui'
import { permissionReasonKey } from '../../localization/presentation'

type Result = { effective_bits: string; warnings: string[]; trace: Array<{ step: string; reason_key: string; after: string }>; outcome: string }

export function PermissionsScreen() {
  const { t } = useTranslation(); const { guild } = useOutletContext<DashboardContext>(); const [mode, setMode] = useState('VIEW_AS_MEMBER'); const [subject, setSubject] = useState(''); const [resource, setResource] = useState(''); const [result, setResult] = useState<Result | null>(null); const [expert, setExpert] = useState(false)
  async function explain() { const body = { view_as: mode, subject_id: mode === 'VIEW_AS_MEMBER' ? subject : null, role_id: mode === 'VIEW_AS_ROLE' ? subject : null, resource_id: resource || null }; setResult(await apiRequest<Result>(`/api/v1/guilds/${guild.guild_id}/permissions/explain`, { method: 'POST', body })) }
  return <section><div className="page-heading"><h1>{t('permissions.title')}</h1><Button labelKey={expert ? 'permissions.simple' : 'permissions.expert'} onClick={() => setExpert(!expert)} /></div><div className="form-grid"><Select labelKey="permissions.viewAs" value={mode} onChange={(event) => setMode(event.target.value)}><option value="VIEW_AS_MEMBER">{t('permissions.member')}</option><option value="VIEW_AS_ROLE">{t('permissions.role')}</option><option value="VIEW_AS_NEWCOMER">{t('permissions.newcomer')}</option></Select>{mode !== 'VIEW_AS_NEWCOMER' && <Input labelKey="permissions.subject" value={subject} pattern="[1-9][0-9]{0,19}" onChange={(event) => setSubject(event.target.value)} />}<Input labelKey="permissions.resource" value={resource} pattern="[1-9][0-9]{0,19}" onChange={(event) => setResource(event.target.value)} /><Button labelKey="permissions.explain" variant="primary" onClick={() => void explain()} /></div>{result && <article className="result-card"><h2>{t('permissions.explain')}</h2><p>{t('permissions.result', { value: result.effective_bits })}</p>{result.warnings.map((warning) => <Badge tone="warning" key={warning}>{t(warning === 'permissions.warning.administratorBypassesOverwrites' ? 'permissions.adminWarning' : 'permissions.warning.generic')}</Badge>)}{expert && <ol>{result.trace.map((item, index) => <li key={`${item.step}-${index}`}>{t(permissionReasonKey(item.reason_key))}</li>)}</ol>}</article>}</section>
}
