import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { apiRequest } from '../../api/client'
import type { DiscordSnowflake } from '../../shared/discord-id'
import { Badge } from '../../shared/components/ui'

type LogicalGroupResource = { resource_type: 'CATEGORY' | 'CHANNEL' | 'ROLE'; discord_channel_id?: string | null; discord_role_id?: string | null; semantic_role?: string | null }
type LogicalGroup = {
  id: string
  guild_id: DiscordSnowflake
  name: string
  slug: string
  description: string | null
  metadata_json?: Record<string, unknown>
  resources?: LogicalGroupResource[]
}

export function LogicalGroupsPanel({ guildId, userId, canWrite }: { guildId: DiscordSnowflake; userId: DiscordSnowflake; canWrite: boolean }) {
  const { t } = useTranslation()
  const client = useQueryClient()
  const queryKey = ['did', userId, guildId, 'logical-groups'] as const
  const query = useQuery({ queryKey, queryFn: () => apiRequest<{ guild_id: string; resource_kind: 'DID_LOGICAL_RESOURCE'; groups: LogicalGroup[] }>(`/api/v1/guilds/${guildId}/logical-groups`) })
  const [editing, setEditing] = useState<LogicalGroup | null>(null)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)

  async function save() {
    if (!editing || draft.length === 0 || draft.length > 128) return
    setBusy(true)
    setFailed(false)
    try {
      await apiRequest(`/api/v1/guilds/${guildId}/logical-groups/${editing.id}`, {
        method: 'PATCH',
        body: { name: draft, description: editing.description, metadata: editing.metadata_json ?? {} },
      })
      await client.invalidateQueries({ queryKey })
      setEditing(null)
    } catch {
      setFailed(true)
    } finally {
      setBusy(false)
    }
  }

  const groups = query.data?.groups ?? []
  if (query.isLoading || groups.length === 0) return null
  return (
    <section className="logical-groups-panel" aria-label={t('structure.logicalGroups.title')}>
      <div className="logical-groups-heading">
        <div><strong>{t('structure.logicalGroups.title')}</strong><small>{t('structure.logicalGroups.help')}</small></div>
        <Badge>{t('structure.logicalGroups.dashboardOnly')}</Badge>
      </div>
      <div className="logical-groups-list">
        {groups.map((group) => (
          <article className="logical-group-row" key={group.id} data-logical-group-id={group.id}>
            <span className="logical-group-icon" aria-hidden="true">◇</span>
            {editing?.id === group.id ? (
              <div className="logical-group-editor">
                <input autoFocus aria-label={t('structure.logicalGroups.label')} value={draft} maxLength={128} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') void save(); if (event.key === 'Escape') setEditing(null) }} />
                <button type="button" disabled={busy || draft.length === 0} onClick={() => void save()}>{t('structure.naming.confirm')}</button>
                <button type="button" onClick={() => setEditing(null)}>{t('structure.naming.cancel')}</button>
                {failed && <small role="alert">{t('errors.generic', { requestId: 'unknown' })}</small>}
              </div>
            ) : (
              <div className="logical-group-copy"><strong>{group.name}</strong><small>{t('structure.logicalGroups.identity', { slug: group.slug })}</small></div>
            )}
            {editing?.id !== group.id && <button type="button" className="logical-group-edit" disabled={!canWrite} title={!canWrite ? t('actions.disabled.capability') : undefined} onClick={() => { setEditing(group); setDraft(group.name); setFailed(false) }}>{t('structure.logicalGroups.edit')}</button>}
          </article>
        ))}
      </div>
    </section>
  )
}
