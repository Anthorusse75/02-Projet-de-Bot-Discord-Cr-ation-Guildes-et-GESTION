import { useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import type { DashboardContext } from '../../app/AppShell'
import { Button, Input, Select, Status } from '../../shared/components/ui'
import { useInteractionStore } from '../../shared/state/interaction'
import { createActionIntent, dispatchAction } from '../interaction/dispatcher'
import type { ResourceRef } from '../interaction/actions'

export function CloneScreen() {
  const { t } = useTranslation(); const { guild,guilds } = useOutletContext<DashboardContext>(); const storedIntent = useInteractionStore((state) => state.previewIntent); const setStoredIntent = useInteractionStore((state) => state.setPreview)
  const prefilled = storedIntent?.source[0]; const [sourceId,setSourceId] = useState(prefilled?.id ?? ''); const [sourceType,setSourceType] = useState<'CHANNEL'|'CATEGORY'>(prefilled?.type === 'CATEGORY' ? 'CATEGORY' : 'CHANNEL'); const [destination,setDestination] = useState(storedIntent?.destination?.guildId ?? guilds.find((item)=>item.guild_id!==guild.guild_id)?.guild_id ?? guild.guild_id); const [resultPlan,setResultPlan] = useState<string|null>(null)
  async function preview() { const destinationGuild = guilds.find((item) => item.guild_id === destination); if (!destinationGuild) return; const source: ResourceRef = { id: sourceId, name: prefilled?.name ?? sourceId, type: sourceType, guildId: guild.guild_id }; const target: ResourceRef = { id: destinationGuild.guild_id, name: destinationGuild.name, type: 'GUILD', guildId: destinationGuild.guild_id }; const intent = createActionIntent('copy', [source], target); const result = await dispatchAction(intent, guild.guild_id); setStoredIntent(null); setResultPlan(result.kind === 'TRANSFER' ? result.planId ?? null : null) }
  return <section><h1>{t('clone.title')}</h1><p>{t('clone.neverMove')}</p><div className="form-grid"><Select labelKey="structure.properties" value={sourceType} onChange={(event)=>setSourceType(event.target.value as 'CHANNEL'|'CATEGORY')}><option value="CHANNEL">{t('structure.channel')}</option><option value="CATEGORY">{t('structure.category')}</option></Select><Input labelKey="permissions.resource" value={sourceId} pattern="[1-9][0-9]{0,19}" onChange={(event)=>setSourceId(event.target.value)}/><Select labelKey="clone.destination" value={destination} onChange={(event)=>setDestination(event.target.value as typeof destination)}>{guilds.filter((item)=>item.guild_id!==guild.guild_id).map((item)=><option value={item.guild_id} key={item.guild_id}>{item.name}</option>)}</Select><Button labelKey="common.preview" variant="primary" disabled={!sourceId || destination === guild.guild_id} onClick={()=>void preview()} /></div>{resultPlan!==null&&<Status>{t('clone.previewReady')} <code>{resultPlan}</code></Status>}</section>
}
