import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { apiRequest } from '../../../api/client'
import { usePolicies, useRoles, useStructure } from '../../../api/queries'
import type { LogicalGroup, Policy, PolicyPreview } from '../../../api/types'
import type { DashboardContext } from '../../../app/AppShell'
import { Badge, ErrorState, Skeleton } from '../../../shared/components/ui'
import type { MessageKey } from '../../../localization/catalog'
import { createValidatedAccessPlan, type AccessPlanNode, type AccessPlanResult } from '../../access/planDraft'
import { apiProblem } from '../../policies/errors'
import { compatibleNativePolicies, createDefinitionFromNative, isPolicyCompatible, nativePolicies, type NativePolicyId } from '../../policies/catalog'
import { buildPolicyTargets, targetKey } from '../../policies/targets'
import type { WizardStep } from '../core/reducer'
import { useWizard } from '../core/useWizard'
import { WizardShell } from '../core/WizardShell'
import { RoleMultiSelect, type ProposedRole } from '../core/RoleMultiSelect'

interface AccessSpaceAnswers {
  targetKey: string | null
  nativeId: NativePolicyId | null
  roleIds: string[]
  proposedRoles: ProposedRole[]
  name: string
  description: string
  policyId: string | null
  policyRevision: number | null
  preview: PolicyPreview | null
  rolePlan: AccessPlanResult | null
}

const initialAnswers: AccessSpaceAnswers = {
  targetKey: null, nativeId: null, roleIds: [], proposedRoles: [], name: '', description: '',
  policyId: null, policyRevision: null, preview: null, rolePlan: null,
}

const steps: readonly WizardStep<AccessSpaceAnswers>[] = [
  { id: 'target', titleKey: 'wizard.accessSpace.step.target', isComplete: (a) => a.targetKey !== null },
  { id: 'intent', titleKey: 'wizard.accessSpace.step.intent', isComplete: (a) => a.nativeId !== null },
  { id: 'roles', titleKey: 'wizard.accessSpace.step.roles', isComplete: (a) => a.roleIds.length > 0 },
  { id: 'conflicts', titleKey: 'wizard.accessSpace.step.conflicts', isComplete: () => true },
  { id: 'adjust', titleKey: 'wizard.accessSpace.step.adjust', isComplete: (a) => a.name.trim().length > 0 },
  { id: 'preview', titleKey: 'wizard.accessSpace.step.preview', isComplete: (a) => a.preview !== null && a.policyId !== null },
  { id: 'plan', titleKey: 'wizard.accessSpace.step.plan', isComplete: () => false },
]

/**
 * REQ-WIZ-{001..010,013,014}, REQ-POL-043: guided assistant that only ever proposes a DRAFT
 * Policy and converges to the canonical Policy→Plan routes. It never calls Discord directly and
 * never activates a Policy — activation and APPLY remain the Policies workspace's and Phase 5's.
 */
export function AccessSpaceWizardScreen() {
  const { t } = useTranslation()
  const { me, guild, capabilities } = useOutletContext<DashboardContext>()
  const navigate = useNavigate()
  const client = useQueryClient()
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const canRead = capabilities?.user_capabilities['policies.read']?.outcome ?? 'UNKNOWN'
  const canCreatePolicy = capabilities?.user_capabilities['policies.create']?.outcome ?? 'UNKNOWN'
  const canPreparePolicyPlan = capabilities?.user_capabilities['policies.activate']?.outcome === 'CAN'
    && capabilities?.user_capabilities['plans.create']?.outcome === 'CAN'
  const canPrepareRolePlan = capabilities?.user_capabilities['roles.write']?.outcome === 'CAN'
    && capabilities?.user_capabilities['plans.create']?.outcome === 'CAN'
    && capabilities?.bot_operations.CREATE_ROLE?.outcome === 'CAN'
  const workspaceEnabled = canRead === 'CAN'

  const policiesQuery = usePolicies(me.user.discord_user_id, guild.guild_id, workspaceEnabled)
  const rolesQuery = useRoles(me.user.discord_user_id, guild.guild_id, workspaceEnabled)
  const structureQuery = useStructure(me.user.discord_user_id, guild.guild_id, false, workspaceEnabled)
  const groupsQuery = useQuery({
    enabled: workspaceEnabled,
    queryKey: ['did', me.user.discord_user_id, guild.guild_id, 'logical-groups'],
    queryFn: () => apiRequest<{ groups: LogicalGroup[] }>(`/api/v1/guilds/${guild.guild_id}/logical-groups`),
  })

  const allRoles = useMemo(() => [...(rolesQuery.data?.roles ?? [])].sort((a, b) => b.position - a.position), [rolesQuery.data])
  const targets = useMemo(
    () => buildPolicyTargets(guild, allRoles.filter((role) => !role.managed), groupsQuery.data?.groups, structureQuery.data),
    [groupsQuery.data, guild, allRoles, structureQuery.data],
  )
  const channelTypes = useMemo(
    () => new Map(targets.filter((target) => target.scopeType === 'CHANNEL' && target.scopeId).map((target) => [target.scopeId as string, target.kind === 'VOICE_CHANNEL' ? 2 : 0])),
    [targets],
  )

  const wizard = useWizard<AccessSpaceAnswers>(steps, initialAnswers)
  const { answers, updateAnswers, currentStep } = wizard

  const selectedTarget = targets.find((target) => targetKey(target) === answers.targetKey) ?? null
  const activeNative = nativePolicies.find((native) => native.id === answers.nativeId) ?? null
  const compatiblePolicies = (policiesQuery.data?.policies ?? []).filter((policy) => isPolicyCompatible(policy, selectedTarget, channelTypes))

  function cancel() {
    navigate(`/guild/${guild.guild_id}/wizards`)
  }

  async function createDraftAndPreview() {
    if (!selectedTarget || !activeNative) return
    setBusy(true); setProblem(null); setNotice(null)
    try {
      let policyId = answers.policyId
      let revision = answers.policyRevision
      if (!policyId) {
        const definition = createDefinitionFromNative(activeNative, selectedTarget, answers.roleIds, { name: answers.name, description: answers.description })
        const created = await apiRequest<Policy>(`/api/v1/guilds/${guild.guild_id}/policies`, {
          method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() }, body: definition,
        })
        policyId = created.policy_id
        revision = created.revision
        await client.invalidateQueries({ queryKey: ['did', me.user.discord_user_id, guild.guild_id, 'policies'] })
        setNotice(t('wizard.accessSpace.preview.draftCreated'))
      }
      const preview = await apiRequest<PolicyPreview>(`/api/v1/guilds/${guild.guild_id}/policies/${policyId}/preview`, { method: 'POST' })
      updateAnswers({ policyId, policyRevision: revision, preview })
    } catch (error) { setProblem(apiProblem(error, t)) }
    finally { setBusy(false) }
  }

  function planBlocker(): string | null {
    if (!answers.preview || !answers.policyId) return t('wizard.accessSpace.plan.previewFirst')
    if (!canPreparePolicyPlan) return t('policies.error.prepareDenied')
    if (answers.preview.impact.accuracy !== 'EXACT') return t('policies.plan.exactRequired')
    if (answers.preview.entries.some((entry) => entry.proposed.outcome === 'BLOCKED' || entry.proposed.outcome === 'UNKNOWN')) return t('policies.plan.unresolved')
    return null
  }

  async function preparePolicyPlan() {
    const blocker = planBlocker(); if (blocker) { setProblem(blocker); return }
    if (!answers.policyId || answers.policyRevision === null) return
    setBusy(true); setProblem(null)
    try {
      await apiRequest(`/api/v1/guilds/${guild.guild_id}/policies/${answers.policyId}/plan`, {
        method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() }, body: { expected_revision: answers.policyRevision },
      })
      navigate(`/guild/${guild.guild_id}/plans`)
    } catch (error) { setProblem(apiProblem(error, t)) }
    finally { setBusy(false) }
  }

  async function prepareRolePlan() {
    if (answers.proposedRoles.length === 0 || !canPrepareRolePlan) return
    setBusy(true); setProblem(null)
    try {
      const nodes: AccessPlanNode[] = answers.proposedRoles.map((role) => ({
        logical_key: `ui.wizard.role.create.${role.id}`,
        resource_type: 'ROLE',
        symbol: `role-${role.id}`,
        properties: { name: role.name, permissions: '0' },
      }))
      const result = await createValidatedAccessPlan(guild.guild_id, nodes)
      updateAnswers({ rolePlan: result })
    } catch (error) { setProblem(apiProblem(error, t)) }
    finally { setBusy(false) }
  }

  if (!capabilities) return <Skeleton />
  if (!workspaceEnabled) return <section className="access-page"><p className="access-callout danger" role="alert">{t('policies.error.denied')}</p></section>
  if (policiesQuery.isLoading || rolesQuery.isLoading || structureQuery.isLoading) return <Skeleton />
  if (policiesQuery.isError || rolesQuery.isError || structureQuery.isError) {
    return <ErrorState retry={() => { void policiesQuery.refetch(); void rolesQuery.refetch(); void structureQuery.refetch() }} />
  }

  const roleAudienceUnresolvable = answers.proposedRoles.length > 0 && answers.roleIds.length === 0

  return (
    <section className="access-page wizard-page">
      <header className="access-hero">
        <div><p className="access-eyebrow">{t('access.eyebrow')}</p><h1>{t('wizard.accessSpace.title')}</h1><p>{t('wizard.accessSpace.subtitle')}</p></div>
      </header>

      <WizardShell
        steps={steps}
        stepIndex={wizard.stepIndex}
        furthestIndex={wizard.furthestIndex}
        canGoNext={wizard.canGoNext}
        canGoBack={wizard.canGoBack}
        busy={busy}
        nextLabelKey="wizard.next"
        onGoToStep={wizard.goToStep}
        onBack={wizard.goBack}
        onNext={wizard.goNext}
        onCancel={cancel}
        cancelLabelKey={answers.policyId ? 'wizard.cancelKeepDraft' : 'wizard.cancelDiscard'}
      >
        {currentStep.id === 'target' && (
          <div className="wizard-step-body">
            <p>{t('wizard.accessSpace.target.help')}</p>
            <label className="field">
              <span>{t('policies.target.label')}</span>
              <select value={answers.targetKey ?? ''} onChange={(event) => updateAnswers(
                { targetKey: event.target.value },
                ['nativeId', 'roleIds', 'proposedRoles', 'name', 'description', 'policyId', 'policyRevision', 'preview', 'rolePlan'],
              )}>
                <option value="" disabled>{t('wizard.accessSpace.target.placeholder')}</option>
                {targets.map((target) => <option key={targetKey(target)} value={targetKey(target)}>{t(`policies.target.kind.${target.kind}` as MessageKey)} · {target.label}</option>)}
              </select>
            </label>
          </div>
        )}

        {currentStep.id === 'intent' && (
          <div className="wizard-step-body">
            <p>{t('wizard.accessSpace.intent.help')}</p>
            <div className="policy-card-list">
              {compatibleNativePolicies(selectedTarget?.kind ?? null).map((native) => (
                <button
                  type="button"
                  key={native.id}
                  className={answers.nativeId === native.id ? 'policy-card selected' : 'policy-card'}
                  onClick={() => updateAnswers(
                    { nativeId: native.id, name: t(native.titleKey as MessageKey), description: t(native.summaryKey as MessageKey) },
                    ['policyId', 'policyRevision', 'preview', 'rolePlan'],
                  )}
                >
                  <strong>{t(native.titleKey as MessageKey)}</strong>
                  <span>{t(native.summaryKey as MessageKey)}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {currentStep.id === 'roles' && (
          <div className="wizard-step-body">
            <p>{activeNative ? t(activeNative.helpKey as MessageKey) : t('wizard.accessSpace.roles.help')}</p>
            <RoleMultiSelect
              roles={allRoles}
              selectedRoleIds={answers.roleIds}
              proposedRoles={answers.proposedRoles}
              disabled={busy}
              suggestedName={t('wizard.accessSpace.roles.suggestedName')}
              onToggleRole={(roleId) => updateAnswers(
                { roleIds: answers.roleIds.includes(roleId) ? answers.roleIds.filter((id) => id !== roleId) : [...answers.roleIds, roleId] },
                ['policyId', 'policyRevision', 'preview'],
              )}
              onAddProposedRole={(role) => updateAnswers({ proposedRoles: [...answers.proposedRoles, role] }, ['rolePlan'])}
              onRemoveProposedRole={(id) => updateAnswers({ proposedRoles: answers.proposedRoles.filter((role) => role.id !== id) }, ['rolePlan'])}
            />
            {roleAudienceUnresolvable && (
              <div className="access-callout danger" role="alert">
                <strong>{t('capability.badge.cannot')}</strong>
                <p>{t('wizard.accessSpace.roles.blockedByProposal')}</p>
              </div>
            )}
          </div>
        )}

        {currentStep.id === 'conflicts' && (
          <div className="wizard-step-body">
            <p>{t('wizard.accessSpace.conflicts.help')}</p>
            {compatiblePolicies.length === 0
              ? <p className="access-help">{t('wizard.accessSpace.conflicts.empty')}</p>
              : <ul className="wizard-conflict-list">
                {compatiblePolicies.map((policy) => (
                  <li key={policy.policy_id}>
                    <strong>{policy.name}</strong>
                    <Badge tone={policy.lifecycle_state === 'ACTIVE' ? 'ok' : 'neutral'}>{t(`policies.lifecycle.${policy.lifecycle_state}` as MessageKey)}</Badge>
                  </li>
                ))}
              </ul>}
            <p className="access-help">{t('wizard.accessSpace.conflicts.disclaimer')}</p>
          </div>
        )}

        {currentStep.id === 'adjust' && (
          <div className="wizard-step-body">
            <label className="field">
              <span>{t('policies.editor.name')}</span>
              <input value={answers.name} onChange={(event) => updateAnswers({ name: event.target.value }, ['policyId', 'policyRevision', 'preview'])} />
            </label>
            <label className="field">
              <span>{t('policies.editor.description')}</span>
              <textarea value={answers.description} onChange={(event) => updateAnswers({ description: event.target.value }, ['policyId', 'policyRevision', 'preview'])} />
            </label>
            <div className="policy-human-result">
              <strong>{t('policies.result.title')}</strong>
              {(activeNative?.access ?? []).map((access) => <span key={access}>{t(`policies.access.${access}` as MessageKey)}</span>)}
              <p>{activeNative?.audienceMode === 'EXCLUDE' ? t('policies.result.excluded') : t('policies.result.others')}</p>
            </div>
          </div>
        )}

        {currentStep.id === 'preview' && (
          <div className="wizard-step-body">
            {!answers.preview ? (
              <div className="policy-preview-empty">
                <p>{t('policies.preview.help')}</p>
                <button type="button" className="button primary" disabled={busy || canCreatePolicy !== 'CAN'} onClick={() => void createDraftAndPreview()}>{t('wizard.accessSpace.preview.action')}</button>
              </div>
            ) : (
              <>
                <div className="access-panel-heading">
                  <div><small>{t('policies.step.preview')}</small><strong>{answers.name}</strong></div>
                  <Badge tone={answers.preview.impact.accuracy === 'EXACT' ? 'ok' : 'warning'}>{t(`policies.accuracy.${answers.preview.impact.accuracy}` as MessageKey)}</Badge>
                </div>
                <div className="policy-impact-grid">
                  <div><strong>{answers.preview.impact.access_gains}</strong><span>{t('policies.impact.gains')}</span></div>
                  <div><strong>{answers.preview.impact.access_losses}</strong><span>{t('policies.impact.losses')}</span></div>
                  <div><strong>{answers.preview.impact.affected_members}</strong><span>{t('policies.impact.members')}</span></div>
                  <div><strong>{answers.preview.impact.conflicts}</strong><span>{t('policies.impact.conflicts')}</span></div>
                </div>
                {answers.preview.impact.diagnostics.map((diagnostic) => <p className="access-callout warning" key={diagnostic}>{t(`policies.diagnostic.${diagnostic}` as MessageKey, { diagnostic })}</p>)}
                <ul className="policy-preview-entries">
                  {answers.preview.entries.map((entry, index) => (
                    <li key={`${entry.target.subject_id}-${index}`} className={entry.proposed.outcome === 'BLOCKED' || entry.proposed.outcome === 'UNKNOWN' ? 'problem' : ''}>
                      <span>{t(`policies.access.${entry.target.requested_access}` as MessageKey)}</span>
                      <Badge tone={entry.proposed.outcome === 'CAN' ? 'ok' : entry.proposed.outcome === 'CANNOT' ? 'danger' : 'warning'}>{t(`policies.outcome.${entry.proposed.outcome}` as MessageKey)}</Badge>
                    </li>
                  ))}
                </ul>
                <button type="button" className="button quiet" disabled={busy} onClick={() => void createDraftAndPreview()}>{t('wizard.accessSpace.preview.refresh')}</button>
              </>
            )}
          </div>
        )}

        {currentStep.id === 'plan' && (
          <div className="wizard-step-body">
            {answers.proposedRoles.length > 0 && (
              <div className="access-panel wizard-role-plan-card">
                <strong>{t('wizard.accessSpace.plan.roleTitle')}</strong>
                <p>{t('wizard.accessSpace.plan.roleHelp')}</p>
                {answers.rolePlan
                  ? <p className="access-callout success" role="status">{t('wizard.accessSpace.plan.roleCreated')}</p>
                  : <button type="button" className="button quiet" disabled={busy || !canPrepareRolePlan} onClick={() => void prepareRolePlan()}>{t('wizard.accessSpace.plan.prepareRole')}</button>}
              </div>
            )}
            <div className="access-panel wizard-policy-plan-card">
              <strong>{t('wizard.accessSpace.plan.policyTitle')}</strong>
              <p>{t('wizard.accessSpace.plan.policyHelp')}</p>
              {planBlocker() && <p className="access-callout danger">{planBlocker()}</p>}
              <button type="button" className="button primary" disabled={busy || Boolean(planBlocker())} onClick={() => void preparePolicyPlan()}>{t('policies.plan.prepare')}</button>
            </div>
          </div>
        )}
      </WizardShell>

      {problem && <p className="access-callout danger" role="alert">{problem}</p>}
      {notice && <p className="access-callout success" role="status">{notice}</p>}
    </section>
  )
}
