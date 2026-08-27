import { useOutletContext } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useCoverage } from '../../api/queries'
import type { DashboardContext } from '../../app/AppShell'
import { Badge, ErrorState, Skeleton } from '../../shared/components/ui'
export function DiagnosticsScreen(){const{t}=useTranslation();const{me,guild}=useOutletContext<DashboardContext>();const query=useCoverage(me.user.discord_user_id,guild.guild_id);if(query.isLoading)return <Skeleton/>;if(query.isError)return <ErrorState retry={()=>void query.refetch()}/>;return <section><h1>{t('diagnostics.title')}</h1><p>{t('diagnostics.source')}</p><article className="result-card"><h2>{t('diagnostics.coverage')}</h2>{Object.entries(query.data??{}).filter(([,v])=>typeof v!=='object').map(([key,value])=><p key={key}><strong>{key}</strong> <Badge>{String(value)}</Badge></p>)}</article></section>}

