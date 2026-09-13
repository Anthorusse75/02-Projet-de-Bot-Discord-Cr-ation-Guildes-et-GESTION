import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useOutletContext, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { apiRequest } from '../../api/client'
import { useGuilds } from '../../api/queries'
import type { Me } from '../../api/types'
import { discordSnowflake } from '../../shared/discord-id'
import { useSessionStore } from '../../shared/state/session'
import { Badge, ErrorState, Skeleton } from '../../shared/components/ui'
import { LanguageSelector } from './LanguageSelector'

type BotOperation = {
  outcome: 'CAN' | 'CANNOT' | 'UNKNOWN'
  required_permissions: string[]
  causes: string[]
  remediations: string[]
  warnings: string[]
}

type OnboardingSnapshot = {
  guild_id: string
  name: string
  installation_status: string
  can_bootstrap: boolean
  bot_present: boolean
  bot_user_id: string | null
  configurator_verified: boolean
  structure_imported: boolean
  channel_count: number
  role_count: number
  coverage: string
  freshness: string
  permissions_checked: boolean
  bot_operations: Record<string, BotOperation>
  initial_audit_complete: boolean
  dashboard_configuration_ready: boolean
  ready_to_activate: boolean
  complete: boolean
  blocked_reason: string | null
}

type StepState = 'done' | 'waiting' | 'blocked'

type Step = {
  key: string
  label: string
  state: StepState
  detail?: string
}

function statusTone(state: StepState): 'ok' | 'warning' | 'danger' {
  if (state === 'done') return 'ok'
  if (state === 'blocked') return 'danger'
  return 'warning'
}

export function OnboardingPage() {
  const { t } = useTranslation()
  const me = useOutletContext<Me>()
  const { guildId } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const setMe = useSessionStore((state) => state.setMe)
  const guilds = useGuilds(me.user.discord_user_id)
  const parsedGuild = guildId ? discordSnowflake(guildId) : null
  const [importQueued, setImportQueued] = useState(false)
  const [busy, setBusy] = useState<'import' | 'activate' | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const query = useQuery({
    enabled: parsedGuild !== null,
    queryKey: ['did', me.user.discord_user_id, parsedGuild ?? 'none', 'onboarding'],
    queryFn: () => apiRequest<OnboardingSnapshot>(`/api/v1/guilds/${parsedGuild}/onboarding`),
    refetchInterval: (state) => {
      if (!importQueued) return false
      return state.state.data?.structure_imported ? false : 1_500
    },
  })

  useEffect(() => {
    if (query.data?.structure_imported) {
      setImportQueued(false)
      setBusy((value) => value === 'import' ? null : value)
    }
  }, [query.data?.structure_imported])

  const guild = guilds.data?.find((item) => item.guild_id === parsedGuild)
  const unavailableOperations = useMemo(
    () => Object.entries(query.data?.bot_operations ?? {}).filter(([, decision]) => decision.outcome !== 'CAN'),
    [query.data?.bot_operations],
  )

  if (!parsedGuild) return null
  if (guilds.isLoading || query.isLoading) return <main className="onboarding-shell"><Skeleton /></main>
  if (guilds.isError || query.isError || !guild) {
    return <main className="onboarding-shell"><ErrorState retry={() => { void guilds.refetch(); void query.refetch() }} /></main>
  }

  const snapshot = query.data
  if (!snapshot) return <main className="onboarding-shell"><Skeleton /></main>

  const blocked = !snapshot.can_bootstrap && !snapshot.complete
  const steps: Step[] = [
    {
      key: 'bot',
      label: t('onboarding.bot'),
      state: snapshot.bot_present ? 'done' : 'waiting',
      detail: snapshot.bot_user_id ? `#${snapshot.bot_user_id}` : undefined,
    },
    {
      key: 'configurator',
      label: t('onboarding.configurator'),
      state: snapshot.configurator_verified ? 'done' : 'blocked',
    },
    {
      key: 'permissions',
      label: t('onboarding.permissions'),
      state: snapshot.permissions_checked ? 'done' : snapshot.bot_present ? 'waiting' : 'blocked',
    },
    {
      key: 'structure',
      label: t('onboarding.structure'),
      state: snapshot.structure_imported ? 'done' : importQueued ? 'waiting' : 'waiting',
      detail: snapshot.structure_imported ? t('onboarding.counts', { channels: snapshot.channel_count, roles: snapshot.role_count }) : undefined,
    },
    {
      key: 'audit',
      label: t('onboarding.audit'),
      state: snapshot.initial_audit_complete ? 'done' : 'waiting',
    },
    {
      key: 'configuration',
      label: t('onboarding.configuration'),
      state: snapshot.dashboard_configuration_ready ? 'done' : 'waiting',
    },
    {
      key: 'activation',
      label: t('onboarding.activation'),
      state: snapshot.complete ? 'done' : snapshot.ready_to_activate ? 'waiting' : blocked ? 'blocked' : 'waiting',
    },
  ]

  function blockedMessage() {
    if (snapshot.blocked_reason === 'BOOTSTRAP_OWNER_OR_ADMINISTRATOR_REQUIRED') return t('onboarding.notAdmin')
    if (snapshot.blocked_reason === 'BOT_GATEWAY_IDENTITY_NOT_OBSERVED') return t('onboarding.gatewayMissing')
    if (snapshot.blocked_reason === 'INITIAL_STRUCTURE_IMPORT_REQUIRED') return t('onboarding.importRequired')
    if (snapshot.blocked_reason === 'BOT_PERMISSIONS_NOT_VERIFIED') return t('onboarding.permissionsPending')
    return null
  }

  async function importStructure() {
    setActionError(null)
    setBusy('import')
    try {
      await apiRequest(`/api/v1/guilds/${parsedGuild}/onboarding/import`, { method: 'POST' })
      setImportQueued(true)
      await query.refetch()
    } catch {
      setBusy(null)
      setActionError(t('errors.network.offline'))
    }
  }

  async function openDashboard() {
    setActionError(null)
    try {
      const selected = await apiRequest<{guild_id:string;csrf_token:string;policy_version:number}>(`/api/v1/guilds/${parsedGuild}/select`, { method: 'POST' })
      const updated: Me = {
        ...me,
        active_guild_id: discordSnowflake(selected.guild_id),
        csrf_token: selected.csrf_token,
        policy_version: selected.policy_version,
      }
      setMe(updated)
      queryClient.setQueryData(['did', 'identity'], updated)
      await queryClient.invalidateQueries({ queryKey: ['did', me.user.discord_user_id, 'guilds'] })
      navigate(`/guild/${parsedGuild}/overview`)
    } catch {
      setActionError(t('errors.authorization.denied'))
    }
  }

  async function activate() {
    setActionError(null)
    setBusy('activate')
    try {
      const result = await apiRequest<OnboardingSnapshot>(`/api/v1/guilds/${parsedGuild}/onboarding/activate`, { method: 'POST' })
      queryClient.setQueryData(['did', me.user.discord_user_id, parsedGuild, 'onboarding'], result)
      await queryClient.invalidateQueries({ queryKey: ['did', me.user.discord_user_id, 'guilds'] })
      await openDashboard()
    } catch {
      setBusy(null)
      setActionError(t('errors.onboarding.notReady'))
      await query.refetch()
    }
  }

  return (
    <main className="onboarding-shell">
      <div className="onboarding-topbar">
        <button type="button" className="back-button" onClick={() => navigate('/guilds')} aria-label={t('guilds.title')}>←</button>
        <div className="onboarding-brand"><span className="brand-mark">D</span><span>DID</span></div>
        <LanguageSelector />
      </div>

      <section className="onboarding-card">
        <header className="onboarding-heading">
          <div className="server-emblem" aria-hidden="true">{guild.name.slice(0, 2).toUpperCase()}</div>
          <div>
            <p className="eyebrow">{guild.name}</p>
            <h1>{t('onboarding.title')}</h1>
            <p>{t('onboarding.subtitle')}</p>
          </div>
          <Badge tone={snapshot.complete ? 'ok' : blocked ? 'danger' : 'warning'}>
            {snapshot.complete ? t('guilds.active') : blocked ? t('onboarding.blocked') : t('guilds.pending')}
          </Badge>
        </header>

        <div className="onboarding-progress-line" aria-hidden="true">
          <span style={{ width: `${Math.round((steps.filter((step) => step.state === 'done').length / steps.length) * 100)}%` }} />
        </div>

        <div className="onboarding-steps">
          {steps.map((step, index) => (
            <article className={`onboarding-step ${step.state}`} key={step.key}>
              <div className="step-index">{step.state === 'done' ? '✓' : index + 1}</div>
              <div className="step-copy">
                <strong>{step.label}</strong>
                {step.detail && <small>{step.detail}</small>}
              </div>
              <Badge tone={statusTone(step.state)}>
                {t(step.state === 'done' ? 'onboarding.done' : step.state === 'blocked' ? 'onboarding.blocked' : 'onboarding.waiting')}
              </Badge>
            </article>
          ))}
        </div>

        {blockedMessage() && <div className="onboarding-callout danger" role="alert">{blockedMessage()}</div>}
        {importQueued && !snapshot.structure_imported && <div className="onboarding-callout">{t('onboarding.importing')}</div>}
        {unavailableOperations.length > 0 && snapshot.permissions_checked && (
          <div className="onboarding-callout warning">
            <strong>{t('onboarding.limited')}</strong>
            <div className="permission-chip-row">
              {unavailableOperations.slice(0, 6).map(([operation, decision]) => (
                <span className="permission-chip" key={operation} title={decision.causes.join(', ')}>
                  {operation.replaceAll('_', ' ')} · {decision.outcome}
                </span>
              ))}
            </div>
          </div>
        )}
        {actionError && <div className="onboarding-callout danger" role="alert">{actionError}</div>}

        <footer className="onboarding-actions">
          <button type="button" className="button quiet" onClick={() => void query.refetch()}>{t('onboarding.refresh')}</button>
          {!snapshot.structure_imported && !snapshot.complete && (
            <button type="button" className="button primary" disabled={!snapshot.can_bootstrap || !snapshot.bot_present || busy !== null} onClick={() => void importStructure()}>
              {busy === 'import' ? t('onboarding.importing') : t('onboarding.import')}
            </button>
          )}
          {snapshot.ready_to_activate && !snapshot.complete && (
            <button type="button" className="button primary" disabled={busy !== null} onClick={() => void activate()}>
              {t('onboarding.activate')}
            </button>
          )}
          {snapshot.complete && (
            <button type="button" className="button primary" onClick={() => void openDashboard()}>{t('guilds.select')}</button>
          )}
        </footer>
      </section>
    </main>
  )
}
