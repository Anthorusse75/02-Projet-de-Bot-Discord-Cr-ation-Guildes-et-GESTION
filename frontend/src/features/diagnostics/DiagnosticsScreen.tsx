import { useOutletContext } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useCoverage } from '../../api/queries'
import type { DashboardContext } from '../../app/AppShell'
import { Badge, ErrorState, Skeleton } from '../../shared/components/ui'
import { coverageStateKey } from '../../localization/presentation'

export function DiagnosticsScreen() {
  const { t } = useTranslation(); const { me, guild } = useOutletContext<DashboardContext>(); const query = useCoverage(me.user.discord_user_id, guild.guild_id)
  if (query.isLoading) return <Skeleton />
  if (query.isError) return <ErrorState retry={() => void query.refetch()} />
  return <section><h1>{t('diagnostics.title')}</h1><p>{t('diagnostics.source')}</p><article className="result-card"><h2>{t('diagnostics.coverage')}</h2><p><strong>{t('diagnostics.mode')}</strong> <Badge>{t(coverageStateKey(query.data?.mode))}</Badge></p><p><strong>{t('diagnostics.freshness')}</strong> <Badge>{t(coverageStateKey(query.data?.freshness))}</Badge></p></article></section>
}
