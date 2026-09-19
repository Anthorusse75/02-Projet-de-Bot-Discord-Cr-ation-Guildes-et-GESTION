import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useOutletContext, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { apiRequest } from '../../api/client'
import { usePolicies, useRoles, useStructure } from '../../api/queries'
import { tenantSignal } from '../../api/tenantLifecycle'
import type { AccessMatrixCell, AccessMatrixResult, BulkPolicyPlan, BulkPolicyPreview, PolicyPreview } from '../../api/types'
import type { DashboardContext } from '../../app/AppShell'
import { Badge, ErrorState, Skeleton } from '../../shared/components/ui'
import { apiProblem } from '../policies/errors'
import { compatibleNativePolicies, createDefinitionFromNative, nativePolicies, type PolicyTarget } from '../policies/catalog'
import { analyzeBulkCompatibility, compatibleBulkPolicies, summarizeBulkPreviews, toggleResourceSelection } from './bulk'
import { MAX_MATRIX_RESOURCES, MAX_MATRIX_ROLES, cellIsUnknown, cellKey, matchesFilter, synthesisLabelKey, type MatrixFilter } from './cells'
import { computePrivateResourceIds } from './privateZones'
import { buildMatrixResources, type MatrixResource } from './resources'

function target(resource: MatrixResource): PolicyTarget {
  return {
    kind: resource.kind,
    scopeType: resource.kind === 'CATEGORY' ? 'CATEGORY' : 'CHANNEL',
    scopeId: resource.id,
    label: resource.label,
  }
}

function matrixKey(event: KeyboardEvent<HTMLButtonElement>, row: number, column: number, columns: number) {
  const moves: Record<string, [number, number]> = { ArrowLeft: [0, -1], ArrowRight: [0, 1], ArrowUp: [-1, 0], ArrowDown: [1, 0] }
  const move = moves[event.key]
  if (!move) return
  event.preventDefault()
  const nextRow = row + move[0]
  const nextColumn = column + move[1]
  if (nextRow < 0 || nextColumn < 0 || nextColumn >= columns) return
  document.querySelector<HTMLButtonElement>(`[data-matrix-row="${nextRow}"][data-matrix-column="${nextColumn}"]`)?.focus()
}

function previewOutcomes(preview: PolicyPreview | undefined, side: 'current' | 'proposed', label: (outcome: string) => string): string {
  if (!preview) return '—'
  return [...new Set(preview.entries.map((entry) => label(entry[side].outcome)))].join(' / ') || '—'
}

export function MatrixScreen() {
  const { t } = useTranslation()
  const { me, guild, capabilities } = useOutletContext<DashboardContext>()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const client = useQueryClient()
  const canRead = capabilities?.user_capabilities['policies.read']?.outcome === 'CAN'
    && capabilities?.user_capabilities['permissions.read']?.outcome === 'CAN'
  const canCreate = capabilities?.user_capabilities['policies.create']?.outcome === 'CAN'
  const canPrepare = capabilities?.user_capabilities['policies.activate']?.outcome === 'CAN'
    && capabilities?.user_capabilities['plans.create']?.outcome === 'CAN'
  const rolesQuery = useRoles(me.user.discord_user_id, guild.guild_id, canRead)
  const structureQuery = useStructure(me.user.discord_user_id, guild.guild_id, false, canRead)
  const policiesQuery = usePolicies(me.user.discord_user_id, guild.guild_id, canRead)
  const allRoles = useMemo(() => (rolesQuery.data?.roles ?? []).filter((role) => !role.managed && role.id !== guild.guild_id), [guild.guild_id, rolesQuery.data])
  const allResources = useMemo(() => buildMatrixResources(structureQuery.data), [structureQuery.data])
  const roles = allRoles.slice(0, MAX_MATRIX_ROLES)
  const resources = allResources.slice(0, MAX_MATRIX_RESOURCES)
  const roleIds = roles.map((role) => role.id)
  const resourceIds = resources.map((resource) => resource.id)
  const matrixQuery = useQuery({
    enabled: canRead && roleIds.length > 0 && resourceIds.length > 0,
    queryKey: ['did', me.user.discord_user_id, guild.guild_id, 'access-matrix', roleIds.join(','), resourceIds.join(',')],
    queryFn: () => apiRequest<AccessMatrixResult>(`/api/v1/guilds/${guild.guild_id}/access-matrix/resolve`, {
      method: 'POST', body: { role_ids: roleIds, resource_ids: resourceIds }, signal: tenantSignal(guild.guild_id),
    }),
  })
  const [filter, setFilter] = useState<MatrixFilter>('ALL')
  const [selectedResourceIds, setSelectedResourceIds] = useState<string[]>([])
  const [activeCell, setActiveCell] = useState<{ cell: AccessMatrixCell; roleName: string; resource: MatrixResource } | null>(null)
  const [cellIntentId, setCellIntentId] = useState<string>('visible_only')
  const [cellResult, setCellResult] = useState<BulkPolicyPreview | null>(null)
  const [cellProblem, setCellProblem] = useState<string | null>(null)
  const [cellNotice, setCellNotice] = useState<string | null>(null)
  const [cellBusy, setCellBusy] = useState(false)
  const [cellDraftKey, setCellDraftKey] = useState(() => crypto.randomUUID())
  const [cellPlanKey, setCellPlanKey] = useState(() => crypto.randomUUID())
  const [detailsOpen, setDetailsOpen] = useState(false)
  const [bulkIntentId, setBulkIntentId] = useState('visible_only')
  const [bulkRoleIds, setBulkRoleIds] = useState<string[]>([])
  const [bulkResult, setBulkResult] = useState<BulkPolicyPreview | null>(null)
  const [bulkPlan, setBulkPlan] = useState<BulkPolicyPlan | null>(null)
  const [bulkProblem, setBulkProblem] = useState<string | null>(null)
  const [bulkBusy, setBulkBusy] = useState(false)
  const [bulkDraftKey, setBulkDraftKey] = useState(() => crypto.randomUUID())
  const [bulkPlanKey, setBulkPlanKey] = useState(() => crypto.randomUUID())
  const appliedResourceRequest = useRef<string | null>(null)

  const requestedResources = searchParams.get('resources') ?? ''
  const requestedResourceIds = useMemo(() => [...new Set(requestedResources.split(',').filter(Boolean))], [requestedResources])
  useEffect(() => {
    if (requestedResourceIds.length < 2 || resources.length === 0) return
    const validIds = requestedResourceIds.filter((id) => resources.some((resource) => resource.id === id))
    if (validIds.length < 2) return
    const requestKey = `${guild.guild_id}:${validIds.join(',')}`
    if (appliedResourceRequest.current === requestKey) return
    appliedResourceRequest.current = requestKey
    setSelectedResourceIds(validIds); setBulkResult(null); setBulkPlan(null); setBulkProblem(null)
    setBulkDraftKey(crypto.randomUUID()); setBulkPlanKey(crypto.randomUUID())
  }, [guild.guild_id, requestedResourceIds, resources])

  const cells = useMemo(() => new Map((matrixQuery.data?.cells ?? []).map((cell) => [cellKey(cell.role_id, cell.resource_id), cell])), [matrixQuery.data])
  const privateIds = useMemo(() => computePrivateResourceIds(policiesQuery.data?.policies ?? [], resources), [policiesQuery.data, resources])
  const filteredResources = resources.filter((resource) => filter === 'PRIVATE'
    ? privateIds.has(resource.id)
    : roles.some((role) => { const cell = cells.get(cellKey(role.id, resource.id)); return cell ? matchesFilter(cell, filter, privateIds) : false }))
  const selectedResources = resources.filter((resource) => selectedResourceIds.includes(resource.id))
  const bulkChoices = compatibleBulkPolicies(nativePolicies, selectedResources)
  const bulkIntent = bulkChoices.find((policy) => policy.id === bulkIntentId) ?? bulkChoices[0]
  const compatibility = bulkIntent ? analyzeBulkCompatibility(bulkIntent, selectedResources) : { compatible: [], excluded: [] }
  const bulkSummary = bulkResult ? summarizeBulkPreviews(bulkResult.items.map((item) => item.preview)) : null
  const bulkBlocked = !bulkSummary || bulkSummary.accuracy !== 'EXACT' || bulkSummary.blocked > 0 || bulkSummary.unknown > 0
  const cellSummary = cellResult ? summarizeBulkPreviews(cellResult.items.map((item) => item.preview)) : null
  const cellBlocked = !cellSummary || cellSummary.accuracy !== 'EXACT' || cellSummary.blocked > 0 || cellSummary.unknown > 0
  const bulkPreviewReason = !canCreate
    ? t('policies.error.editDenied')
    : bulkRoleIds.length === 0
      ? t('policies.error.audienceRequired')
      : compatibility.compatible.length === 0
        ? t('matrix.bulk.noCompatible')
        : null
  const outcomeLabel = (outcome: string) => t(`policies.outcome.${outcome}`)

  function resetBulkOperation(nextSelection = selectedResourceIds) {
    setSelectedResourceIds(nextSelection); setBulkResult(null); setBulkPlan(null); setBulkProblem(null)
    setBulkDraftKey(crypto.randomUUID()); setBulkPlanKey(crypto.randomUUID())
  }

  function openCell(cell: AccessMatrixCell, roleName: string, resource: MatrixResource) {
    const first = compatibleNativePolicies(resource.kind).find((policy) => policy.matrixCompatible !== false)
    setActiveCell({ cell, roleName, resource }); setCellIntentId(first?.id ?? 'staff_only')
    setCellResult(null); setCellProblem(null); setCellNotice(null); setDetailsOpen(false)
    setCellDraftKey(crypto.randomUUID()); setCellPlanKey(crypto.randomUUID())
  }

  async function previewCell() {
    if (!activeCell) return
    const intent = compatibleNativePolicies(activeCell.resource.kind).filter((policy) => policy.matrixCompatible !== false).find((item) => item.id === cellIntentId)
    if (!intent) return
    setCellBusy(true); setCellProblem(null); setCellNotice(null)
    try {
      const definition = createDefinitionFromNative(intent, target(activeCell.resource), [activeCell.cell.role_id], {
        name: `${t(intent.titleKey)} · ${activeCell.resource.label}`, description: t(intent.summaryKey),
      })
      const result = await apiRequest<BulkPolicyPreview>(`/api/v1/guilds/${guild.guild_id}/policies/bulk-preview`, {
        method: 'POST', headers: { 'Idempotency-Key': cellDraftKey }, body: { definitions: [definition] },
      })
      setCellResult(result); setCellNotice(t('matrix.cell.draftReady'))
      await client.invalidateQueries({ queryKey: ['did', me.user.discord_user_id, guild.guild_id, 'policies'] })
    } catch (error) { setCellProblem(apiProblem(error, t)) }
    finally { setCellBusy(false) }
  }

  async function planCell() {
    const policy = cellResult?.items[0]?.policy
    if (!policy) return
    setCellBusy(true); setCellProblem(null)
    try {
      const result = await apiRequest<BulkPolicyPlan>(`/api/v1/guilds/${guild.guild_id}/policies/bulk-plan`, {
        method: 'POST', headers: { 'Idempotency-Key': cellPlanKey },
        body: { policies: [{ policy_id: policy.policy_id, expected_revision: policy.revision }] },
      })
      setCellNotice(t('matrix.plansPrepared', { count: result.prepared_count }))
    } catch (error) { setCellProblem(apiProblem(error, t)) }
    finally { setCellBusy(false) }
  }

  async function previewBulk() {
    if (!bulkIntent || compatibility.compatible.length === 0 || bulkRoleIds.length === 0) return
    setBulkBusy(true); setBulkProblem(null); setBulkResult(null); setBulkPlan(null)
    try {
      const definitions = compatibility.compatible.map((resource) => createDefinitionFromNative(
        bulkIntent, target(resource), bulkRoleIds,
        { name: `${t(bulkIntent.titleKey)} · ${resource.label}`, description: t(bulkIntent.summaryKey) },
      ))
      const result = await apiRequest<BulkPolicyPreview>(`/api/v1/guilds/${guild.guild_id}/policies/bulk-preview`, {
        method: 'POST', headers: { 'Idempotency-Key': bulkDraftKey }, body: { definitions },
      })
      setBulkResult(result)
      await client.invalidateQueries({ queryKey: ['did', me.user.discord_user_id, guild.guild_id, 'policies'] })
    } catch (error) { setBulkProblem(apiProblem(error, t)) }
    finally { setBulkBusy(false) }
  }

  async function planBulk() {
    if (!bulkResult || bulkBlocked) return
    setBulkBusy(true); setBulkProblem(null)
    try {
      const result = await apiRequest<BulkPolicyPlan>(`/api/v1/guilds/${guild.guild_id}/policies/bulk-plan`, {
        method: 'POST', headers: { 'Idempotency-Key': bulkPlanKey },
        body: { policies: bulkResult.items.map(({ policy }) => ({ policy_id: policy.policy_id, expected_revision: policy.revision })) },
      })
      setBulkPlan(result)
    } catch (error) { setBulkProblem(apiProblem(error, t)) }
    finally { setBulkBusy(false) }
  }

  if (!capabilities) return <Skeleton />
  if (!canRead) return <section className="access-page"><p className="access-callout danger" role="alert">{t('matrix.denied')}</p></section>
  if (rolesQuery.isLoading || structureQuery.isLoading || policiesQuery.isLoading) return <Skeleton />
  if (rolesQuery.isError || structureQuery.isError || policiesQuery.isError) return <ErrorState retry={() => { void rolesQuery.refetch(); void structureQuery.refetch(); void policiesQuery.refetch() }} />

  return <section className="access-page matrix-workbench">
    <header className="access-hero"><div><p className="access-eyebrow">{t('access.eyebrow')}</p><h1>{t('matrix.title')}</h1><p>{t('matrix.subtitle')}</p></div><button type="button" className="button quiet" onClick={() => void matrixQuery.refetch()}>{t('matrix.refresh')}</button></header>
    {(allRoles.length > roles.length || allResources.length > resources.length) && <p className="access-callout warning">{t('matrix.limit', { roles: roles.length, resources: resources.length })}</p>}
    <article className="access-panel matrix-toolbar"><div className="matrix-filters" role="group" aria-label={t('matrix.filters.label')}>{(['ALL','CONFLICTS','EXCEPTIONS','PRIVATE'] as MatrixFilter[]).map((value) => <button type="button" key={value} className={filter === value ? 'active' : ''} aria-pressed={filter === value} onClick={() => setFilter(value)}>{t(`matrix.filters.${value}`)}</button>)}</div><div><Badge tone={matrixQuery.data?.freshness === 'FRESH' ? 'ok' : 'warning'}>{matrixQuery.data?.freshness ?? t('common.loading')}</Badge> <span>{t('matrix.selection.count', { count: selectedResourceIds.length })}</span></div></article>

    {matrixQuery.isLoading ? <Skeleton /> : matrixQuery.isError ? <ErrorState retry={() => void matrixQuery.refetch()} /> : roles.length === 0 || resources.length === 0 ? <article className="access-panel"><p>{t('matrix.empty')}</p></article> : <div className="matrix-scroll" role="region" aria-label={t('matrix.grid.label')} tabIndex={0}><table className="access-matrix"><thead><tr><th scope="col">{t('matrix.roles')}</th>{filteredResources.map((resource) => <th scope="col" key={resource.id}><label><input type="checkbox" checked={selectedResourceIds.includes(resource.id)} onChange={() => resetBulkOperation(toggleResourceSelection(selectedResourceIds, resource.id))} /><span>{resource.kind === 'CATEGORY' ? '▣' : resource.kind === 'VOICE_CHANNEL' ? '◉' : '#'} {resource.label}</span></label></th>)}</tr></thead><tbody>{roles.map((role, row) => <tr key={role.id}><th scope="row">{role.name}</th>{filteredResources.map((resource, column) => { const cell = cells.get(cellKey(role.id, resource.id)); if (!cell) return <td key={resource.id}>—</td>; const unknown = cellIsUnknown(cell); return <td key={resource.id}><button type="button" className={`matrix-cell ${unknown ? 'unknown' : ''} ${cell.conflict ? 'conflict' : ''} ${cell.exception ? 'exception' : ''}`} data-matrix-row={row} data-matrix-column={column} onKeyDown={(event) => matrixKey(event, row, column, filteredResources.length)} onClick={() => openCell(cell, role.name, resource)} aria-label={t('matrix.cell.label', { role: role.name, resource: resource.label, access: t(synthesisLabelKey(cell.synthesis)) })}><strong>{t(synthesisLabelKey(cell.synthesis))}</strong><span>{cell.conflict && t('matrix.marker.conflict')}{cell.exception && t('matrix.marker.exception')}{cell.inherited && !cell.exception && t('matrix.marker.inherited')}</span></button></td> })}</tr>)}</tbody></table></div>}

    {activeCell && <article className="access-panel matrix-cell-editor" aria-labelledby="matrix-cell-editor-title"><div className="access-panel-heading"><div><small>{activeCell.roleName} × {activeCell.resource.label}</small><h2 id="matrix-cell-editor-title">{t('matrix.cell.edit')}</h2></div><button type="button" className="button quiet" onClick={() => setActiveCell(null)}>{t('common.close')}</button></div><p>{t('matrix.cell.current', { access: t(synthesisLabelKey(activeCell.cell.synthesis)) })}</p><label className="field"><span>{t('matrix.cell.intent')}</span><select value={cellIntentId} onChange={(event) => { setCellIntentId(event.target.value); setCellResult(null); setCellDraftKey(crypto.randomUUID()); setCellPlanKey(crypto.randomUUID()) }}>{compatibleNativePolicies(activeCell.resource.kind).filter((policy) => policy.matrixCompatible !== false).map((policy) => <option value={policy.id} key={policy.id}>{t(policy.titleKey)}</option>)}</select></label><div className="button-row"><button type="button" className="button primary" disabled={!canCreate || cellBusy} title={!canCreate ? t('policies.error.editDenied') : undefined} onClick={() => void previewCell()}>{cellResult ? t('matrix.preview.refresh') : t('matrix.preview.create')}</button><button type="button" className="button quiet" onClick={() => setDetailsOpen((value) => !value)}>{t('matrix.discordDetails')}</button></div>{detailsOpen && <pre className="matrix-details">{JSON.stringify(activeCell.cell, null, 2)}</pre>}{cellResult && <div className="matrix-before-after"><span>{t('matrix.before')} <strong>{previewOutcomes(cellResult.items[0]?.preview, 'current', outcomeLabel)}</strong></span><span aria-hidden="true">→</span><span>{t('matrix.after')} <strong>{previewOutcomes(cellResult.items[0]?.preview, 'proposed', outcomeLabel)}</strong></span></div>}{cellResult && <button type="button" className="button primary" disabled={!canPrepare || cellBusy || cellBlocked} title={!canPrepare ? t('policies.error.prepareDenied') : cellBlocked ? t('matrix.bulk.resolveFirst') : undefined} onClick={() => void planCell()}>{t('matrix.plan.prepare')}</button>}{cellProblem && <p className="access-callout danger" role="alert">{cellProblem}</p>}{cellNotice && <p className="access-callout success" role="status">{cellNotice}</p>}</article>}

    {selectedResources.length > 0 && <article className="access-panel matrix-bulk"><div className="access-panel-heading"><div><small>{t('matrix.bulk.eyebrow')}</small><strong>{t('matrix.bulk.title')}</strong></div><Badge>{t('matrix.selection.count', { count: selectedResources.length })}</Badge></div><label className="field"><span>{t('matrix.bulk.policy')}</span><select value={bulkIntent?.id ?? ''} onChange={(event) => { setBulkIntentId(event.target.value); setBulkResult(null); setBulkPlan(null); setBulkDraftKey(crypto.randomUUID()); setBulkPlanKey(crypto.randomUUID()) }}>{bulkChoices.map((policy) => <option value={policy.id} key={policy.id}>{t(policy.titleKey)}</option>)}</select></label><fieldset className="matrix-role-picker"><legend>{t('matrix.bulk.audience')}</legend>{roles.map((role) => <label key={role.id}><input type="checkbox" checked={bulkRoleIds.includes(role.id)} onChange={() => { setBulkRoleIds(toggleResourceSelection(bulkRoleIds, role.id)); setBulkResult(null); setBulkPlan(null); setBulkDraftKey(crypto.randomUUID()); setBulkPlanKey(crypto.randomUUID()) }} />{role.name}</label>)}</fieldset><div className="matrix-counts"><span>{t('matrix.bulk.selected', { count: selectedResources.length })}</span><span>{t('matrix.bulk.compatible', { count: compatibility.compatible.length })}</span><span>{t('matrix.bulk.excluded', { count: compatibility.excluded.length })}</span></div>{compatibility.excluded.length > 0 && <ul className="matrix-exclusions">{compatibility.excluded.map(({ resource, reasonKey }) => <li key={resource.id}><strong>{resource.label}</strong> — {t(reasonKey)}</li>)}</ul>}<button type="button" className="button primary" disabled={bulkBusy || Boolean(bulkPreviewReason)} title={bulkPreviewReason ?? undefined} onClick={() => void previewBulk()}>{t('matrix.bulk.preview')}</button>{bulkResult && bulkSummary && <><div className="matrix-counts"><span>{t('matrix.bulk.drafts', { count: bulkResult.draft_count })}</span><span>{t('matrix.bulk.differences', { count: bulkSummary.differences })}</span><span>{t('matrix.bulk.conflicts', { count: bulkSummary.conflicts })}</span><span>{t('matrix.bulk.blocked', { count: bulkSummary.blocked })}</span><span>{t('matrix.bulk.unknown', { count: bulkSummary.unknown })}</span><span>{t('matrix.bulk.accuracy', { accuracy: t(`policies.accuracy.${bulkSummary.accuracy}`) })}</span></div><div className="matrix-resource-previews">{bulkResult.items.map(({ policy, preview }) => <div key={policy.policy_id}><strong>{resources.find((resource) => resource.id === policy.scope_id)?.label ?? policy.name}</strong><span>{t('matrix.before')} {previewOutcomes(preview, 'current', outcomeLabel)} → {t('matrix.after')} {previewOutcomes(preview, 'proposed', outcomeLabel)}</span></div>)}</div><button type="button" className="button primary" disabled={!canPrepare || bulkBusy || bulkBlocked} title={!canPrepare ? t('policies.error.prepareDenied') : bulkBlocked ? t('matrix.bulk.resolveFirst') : undefined} onClick={() => void planBulk()}>{t('matrix.plan.prepare')}</button></>}{bulkPlan && <p className="access-callout success" role="status">{t('matrix.plansPrepared', { count: bulkPlan.prepared_count })} <button type="button" className="button quiet" onClick={() => navigate(`/guild/${guild.guild_id}/plans`)}>{t('nav.plans')}</button></p>}{bulkProblem && <p className="access-callout danger" role="alert">{bulkProblem}</p>}</article>}
  </section>
}
