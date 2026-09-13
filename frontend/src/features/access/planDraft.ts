import { apiRequest } from '../../api/client'
import type { DiscordSnowflake } from '../../shared/discord-id'

export type AccessPlanRelation = {
  name: 'channel' | 'subject' | 'parent'
  kind: 'DISCORD_ID' | 'SYMBOL'
  value: string
}

export type AccessPlanNode = {
  logical_key: string
  resource_type: 'ROLE' | 'OVERWRITE'
  discord_id?: string
  symbol?: string
  presence?: 'PRESENT' | 'ABSENT'
  properties?: Record<string, unknown>
  relations?: AccessPlanRelation[]
}

export type AccessPlanResult = {
  id: string
  state_version: number
  status?: string
  risk_level?: string
  impact?: Record<string, number>
  reinforced_confirmation_required?: boolean
}

export async function createValidatedAccessPlan(
  guildId: DiscordSnowflake,
  nodes: AccessPlanNode[],
): Promise<AccessPlanResult> {
  const created = await apiRequest<{ plan: AccessPlanResult }>(`/api/v1/guilds/${guildId}/plans`, {
    method: 'POST',
    headers: { 'Idempotency-Key': crypto.randomUUID() },
    body: { schema_version: 'did-dsg-v1', nodes },
  })
  const validated = await apiRequest<{ plan: AccessPlanResult }>(`/api/v1/guilds/${guildId}/plans/${created.plan.id}/validate`, {
    method: 'POST',
    body: { expected_version: created.plan.state_version },
  })
  return validated.plan
}
