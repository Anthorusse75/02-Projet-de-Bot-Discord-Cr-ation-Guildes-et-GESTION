import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useOutletContext } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ApiError, apiRequest } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import { usePlanProgress, usePlans } from '../../api/queries'
import type { Plan } from '../../api/types'
import type { DashboardContext } from '../../app/AppShell'
import { Badge, Button, EmptyState, ErrorState, Progress, Skeleton, Status } from '../../shared/components/ui'
import { planStatusKey, progressMessageKey, riskKey } from '../../localization/presentation'
import { useLocale } from '../../localization/runtime'

type PlanCommand = 'validate' | 'confirm' | 'apply' | 'cancel'

export function PlansScreen() {
  const { t } = useTranslation(); const { locale } = useLocale(); const { me, guild, capabilities } = useOutletContext<DashboardContext>()
  const query = usePlans(me.user.discord_user_id, guild.guild_id); const [selected,setSelected] = useState<Plan|null>(null); const [problemKey,setProblemKey] = useState<'errors.plans.conflict'|'errors.generic'|null>(null); const [acceptedJobId,setAcceptedJobId] = useState<string|null>(null)
  const progress = usePlanProgress(me.user.discord_user_id, guild.guild_id, selected?.id); const client = useQueryClient()
  const plansCreate = capabilities?.user_capabilities['plans.create']?.outcome ?? 'UNKNOWN'
  const plansApply = capabilities?.user_capabilities['plans.apply']?.outcome ?? 'UNKNOWN'

  function selectCurrent(plan: Plan) {
    setSelected(plan)
    client.setQueryData<{plans:Plan[]}>(queryKeys.tenant(me.user.discord_user_id, guild.guild_id, 'plans'), (current) => current ? { ...current, plans: current.plans.map((item) => item.id === plan.id ? plan : item) } : current)
  }

  async function refreshSelected() {
    if (!selected) return
    const refreshed = await query.refetch()
    const current = refreshed.data?.plans.find((plan) => plan.id === selected.id)
    if (current) setSelected(current)
  }

  async function command(path: PlanCommand) {
    if (!selected) return
    setProblemKey(null)
    const options: Parameters<typeof apiRequest>[1] = { method: 'POST' }
    if (path === 'validate') options.body = { expected_version: selected.state_version }
    if (path === 'confirm') {
      options.headers = { 'Idempotency-Key': crypto.randomUUID() }
      options.body = { expected_version: selected.state_version, plan_hash: selected.plan_hash, acknowledgement: selected.reinforced_confirmation_required ? `CONFIRM DESTRUCTIVE ${selected.plan_hash}` : null }
    }
    try {
      if (path === 'validate') {
        const response = await apiRequest<{plan:Plan}>(`/api/v1/guilds/${guild.guild_id}/plans/${selected.id}/validate`, options)
        selectCurrent(response.plan)
      } else if (path === 'apply') {
        const response = await apiRequest<{job_id:string}>(`/api/v1/guilds/${guild.guild_id}/plans/${selected.id}/apply`, options)
        setAcceptedJobId(response.job_id)
        await client.invalidateQueries({ queryKey: queryKeys.tenant(me.user.discord_user_id, guild.guild_id, 'plans') })
        await progress.refetch()
      } else {
        const response = await apiRequest<Plan>(`/api/v1/guilds/${guild.guild_id}/plans/${selected.id}/${path}`, options)
        selectCurrent(response)
      }
      await client.invalidateQueries({ queryKey: queryKeys.tenant(me.user.discord_user_id, guild.guild_id, 'plans') })
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setProblemKey('errors.plans.conflict')
        await refreshSelected()
      } else setProblemKey('errors.generic')
    }
  }

  if(query.isLoading)return <Skeleton/>; if(query.isError)return <ErrorState retry={()=>void query.refetch()}/>
  const events = progress.data?.events ?? []; const latest = events.at(-1); const total = latest?.total_operations; const completed = latest?.completed_operations ?? 0; const ratio = total && total > 0 ? completed / total : undefined; const percentage = ratio === undefined ? undefined : Math.round(ratio * 100); const numbers = new Intl.NumberFormat(locale); const percent = new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 0 })
  return <section><h1>{t('plans.title')}</h1>{query.data?.plans.length===0&&<EmptyState messageKey="plans.empty"/>}<div className="card-grid">{query.data?.plans.map((plan)=><button type="button" className="plan-card" key={plan.id} onClick={()=>{setSelected(plan);setAcceptedJobId(null);setProblemKey(null)}}><strong>{plan.id.slice(0,8)}</strong><Badge tone={plan.status==='SUCCEEDED'?'ok':plan.status==='FAILED'?'danger':'neutral'}>{t(planStatusKey(plan.status))}</Badge><span>{t('plans.risk',{value:t(riskKey(plan.risk_level))})}</span></button>)}</div>{selected&&<article className="detail-panel"><h2>{t('plans.progress')}</h2><Progress labelKey="plans.progress" value={percentage}/>{ratio!==undefined&&<p>{t('plans.progress.counts',{completed:numbers.format(completed),total:numbers.format(total??0),percent:percent.format(ratio)})}</p>}{progress.isError&&<ErrorState retry={()=>void progress.refetch()}/>} {acceptedJobId && <Status>{t('plans.apply.accepted')}</Status>}{problemKey&&<p role="alert">{t(problemKey,{requestId:'unknown'})}</p>}<div className="button-row"><Button labelKey="plans.preflight" disabled={plansCreate!=='CAN'} disabledReasonKey={plansCreate==='CANNOT'?'actions.disabled.capability':'actions.disabled.unknown'} onClick={()=>void command('validate')}/><Button labelKey="plans.confirm" disabled={plansApply!=='CAN'} disabledReasonKey={plansApply==='CANNOT'?'actions.disabled.capability':'actions.disabled.unknown'} onClick={()=>void command('confirm')}/><Button labelKey="plans.apply" variant="primary" disabled={plansApply!=='CAN'} disabledReasonKey={plansApply==='CANNOT'?'actions.disabled.capability':'actions.disabled.unknown'} onClick={()=>void command('apply')}/><Button labelKey="plans.cancel" variant="danger" disabled={plansApply!=='CAN'} disabledReasonKey={plansApply==='CANNOT'?'actions.disabled.capability':'actions.disabled.unknown'} onClick={()=>void command('cancel')}/></div><ol aria-live="polite">{events.map((event)=><li key={event.sequence}><Badge>{t(planStatusKey(event.plan_status))}</Badge> {t(progressMessageKey(event.message_key),event.params??{})}</li>)}</ol></article>}</section>
}
