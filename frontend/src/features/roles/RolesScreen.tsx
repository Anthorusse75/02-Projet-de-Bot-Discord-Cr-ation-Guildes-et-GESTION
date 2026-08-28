import { useOutletContext } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useRoles } from '../../api/queries'
import type { DashboardContext } from '../../app/AppShell'
import { Badge, EmptyState, ErrorState, Skeleton } from '../../shared/components/ui'
export function RolesScreen(){const{t}=useTranslation();const{me,guild}=useOutletContext<DashboardContext>();const query=useRoles(me.user.discord_user_id,guild.guild_id);if(query.isLoading)return <Skeleton/>;if(query.isError)return <ErrorState retry={()=>void query.refetch()}/>;return <section><h1>{t('roles.title')}</h1>{query.data?.roles.length===0&&<EmptyState messageKey="roles.empty"/>}<ol className="role-list">{query.data?.roles.sort((a,b)=>b.position-a.position).map((role)=><li key={role.id}><div><strong>{role.name}</strong>{role.managed&&<Badge>{t('roles.managed')}</Badge>}</div><span>{t('roles.permissions',{value:role.permissions})}</span><div><Badge>{t('roles.knownPermissions',{count:role.known_flags.length})}</Badge></div></li>)}</ol></section>}
