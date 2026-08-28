import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useOutletContext } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ApiError } from '../../api/client'
import { useGuildDashboardCapabilities } from '../../api/queries'
import type { DashboardContext } from '../../app/AppShell'
import { Button, Input, Select, Status } from '../../shared/components/ui'
import { useInteractionStore } from '../../shared/state/interaction'
import { createActionIntent, dispatchAction } from '../interaction/dispatcher'
import { resolveActions, type ResourceRef } from '../interaction/actions'

export function CloneScreen() {
  const { t } = useTranslation(); const { me,guild,guilds,capabilities } = useOutletContext<DashboardContext>(); const client = useQueryClient(); const storedIntent = useInteractionStore((state) => state.previewIntent); const setStoredIntent = useInteractionStore((state) => state.setPreview)
  const destinations = guilds.filter((item)=>item.guild_id!==guild.guild_id); const capabilityQueries = useGuildDashboardCapabilities(me.user.discord_user_id, destinations.map((item)=>item.guild_id))
  const prefilled = storedIntent?.source[0]; const [sourceId,setSourceId] = useState(prefilled?.id ?? ''); const [sourceType,setSourceType] = useState<'CHANNEL'|'CATEGORY'>(prefilled?.type === 'CATEGORY' ? 'CATEGORY' : 'CHANNEL'); const [destination,setDestination] = useState(storedIntent?.destination?.guildId ?? destinations[0]?.guild_id ?? guild.guild_id); const [resultPlan,setResultPlan] = useState<string|null>(null); const [problemKey,setProblemKey] = useState<'errors.authorization.denied'|'errors.generic'|null>(null)
  const destinationIndex = destinations.findIndex((item)=>item.guild_id===destination); const destinationGuild = destinations[destinationIndex]; const destinationCapabilities = capabilityQueries[destinationIndex]?.data
  const source: ResourceRef = { id: sourceId, name: prefilled?.name ?? sourceId, type: sourceType, guildId: guild.guild_id }; const target: ResourceRef | undefined = destinationGuild ? { id: destinationGuild.guild_id, name: destinationGuild.name, type: 'GUILD', guildId: destinationGuild.guild_id } : undefined
  const copyAvailability = target && destinationGuild ? resolveActions({ source:[source], destination:target, sourceUserCapabilities:capabilities?.user_capabilities??{}, sourceBotCapabilities:capabilities?.bot_operations??{}, ...(destinationCapabilities?{destinationUserCapabilities:destinationCapabilities.user_capabilities,destinationBotCapabilities:destinationCapabilities.bot_operations}:{}), destinationInstallationStatus:destinationGuild.installation_status }).find((item)=>item.action.id==='copy') : undefined
  async function preview() {
    if (!target || !copyAvailability?.enabled) return
    setProblemKey(null); setResultPlan(null)
    try { const result = await dispatchAction(createActionIntent('copy', [source], target), guild.guild_id); setStoredIntent(null); setResultPlan(result.kind === 'TRANSFER' ? result.planId ?? null : null) }
    catch (error) { setProblemKey(error instanceof ApiError && error.status===403?'errors.authorization.denied':'errors.generic'); await client.invalidateQueries({queryKey:['did',me.user.discord_user_id,destination,'dashboard-capabilities']}) }
  }
  return <section><h1>{t('clone.title')}</h1><p>{t('clone.neverMove')}</p><div className="form-grid"><Select labelKey="structure.properties" value={sourceType} onChange={(event)=>setSourceType(event.target.value as 'CHANNEL'|'CATEGORY')}><option value="CHANNEL">{t('structure.channel')}</option><option value="CATEGORY">{t('structure.category')}</option></Select><Input labelKey="permissions.resource" value={sourceId} pattern="[1-9][0-9]{0,19}" onChange={(event)=>setSourceId(event.target.value)}/><Select labelKey="clone.destination" value={destination} onChange={(event)=>setDestination(event.target.value as typeof destination)}>{destinations.map((item)=><option value={item.guild_id} key={item.guild_id} disabled={item.installation_status!=='ACTIVE'}>{item.name}</option>)}</Select><Button labelKey="common.preview" variant="primary" disabled={!sourceId || destination === guild.guild_id || !copyAvailability?.enabled} {...(copyAvailability?.reasonKey?{disabledReasonKey:copyAvailability.reasonKey}:{})} onClick={()=>void preview()} /></div>{problemKey&&<p role="alert">{t(problemKey,{requestId:'unknown'})}</p>}{resultPlan!==null&&<Status>{t('clone.previewReady')} <code>{resultPlan}</code></Status>}</section>
}
