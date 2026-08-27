import { Navigate, Outlet } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ApiError } from '../../api/client'
import { useMe } from '../../api/queries'
import { LanguageSelector } from '../guilds/LanguageSelector'
import { ErrorState, Skeleton } from '../../shared/components/ui'

export function LoginPage() {
  const { t } = useTranslation(); const me = useMe()
  if (me.isLoading) return <main className="login shell"><Skeleton /></main>
  if (me.data) return <Navigate to={me.data.active_guild_id ? `/guild/${me.data.active_guild_id}/structure` : '/guilds'} replace />
  if (me.error && (!(me.error instanceof ApiError) || me.error.status !== 401)) return <main className="login shell"><ErrorState retry={() => void me.refetch()} /></main>
  return <main id="main" className="login shell"><LanguageSelector /><div className="login-card"><span className="brand-mark">DID</span><h1>{t('app.title')}</h1><p>{t('auth.welcome')}</p><a className="primary-action" href="/auth/discord/login">{t('auth.login')}</a></div></main>
}

export function AuthGate() {
  const me = useMe()
  if (me.isLoading) return <main className="shell"><Skeleton /></main>
  if (!me.data) return <Navigate to="/login" replace />
  return <Outlet context={me.data} />
}

