import { useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import type { DashboardCapabilities, Guild } from '../../api/types'
import { Dialog, Input, MenuItem } from '../../shared/components/ui'
import { useInteractionStore } from '../../shared/state/interaction'
import { resolveActions, type ActionContext, type ResourceRef } from '../interaction/actions'
import { createActionIntent, dispatchAction } from '../interaction/dispatcher'

export function CommandPalette({ guild, capabilities }: { guild: Guild; capabilities: DashboardCapabilities | undefined }) {
  const { t } = useTranslation(); const navigate = useNavigate(); const open = useInteractionStore((state) => state.commandOpen); const setOpen = useInteractionStore((state) => state.setCommandOpen); const selection = useInteractionStore((state) => state.selection); const setPreview = useInteractionStore((state) => state.setPreview); const [search,setSearch] = useState('')
  const returnFocus = useRef<HTMLElement | null>(null); if (open && returnFocus.current === null) returnFocus.current = document.querySelector('.command-trigger')
  const source: ResourceRef[] = selection.length ? selection : [{ id: guild.guild_id, name: guild.name, type: 'GUILD', guildId: guild.guild_id }]
  const context: ActionContext = { source, userCapabilities: capabilities?.user_capabilities ?? {}, botCapabilities: capabilities?.bot_operations ?? {} }
  const items = useMemo(() => resolveActions(context).filter(({ action }) => t(action.labelKey).toLocaleLowerCase().includes(search.toLocaleLowerCase())), [capabilities, search, selection, t])
  async function choose(actionId: string, enabled: boolean) { if (!enabled) return; const intent = createActionIntent(actionId, source); setOpen(false); if (actionId === 'open' || actionId === 'explain') { const result = await dispatchAction(intent, guild.guild_id); navigate(result.path) } else { setPreview(intent); navigate(`/guild/${guild.guild_id}/structure`) } }
  return <Dialog open={open} titleKey="commands.title" onClose={() => setOpen(false)} returnFocus={returnFocus}><Input labelKey="commands.placeholder" autoFocus value={search} onChange={(event) => setSearch(event.target.value)}/><div className="command-list" role="menu">{items.map(({action,enabled,reasonKey}) => <MenuItem key={action.id} disabled={!enabled} disabledReasonKey={reasonKey} onSelect={() => void choose(action.id, enabled)}>{t(action.labelKey)}</MenuItem>)}{items.length===0&&<p>{t('commands.empty')}</p>}</div></Dialog>
}
