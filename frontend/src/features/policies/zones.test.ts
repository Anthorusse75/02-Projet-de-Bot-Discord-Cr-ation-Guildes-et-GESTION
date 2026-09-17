import { describe, expect, it } from 'vitest'
import { discordSnowflake } from '../../shared/discord-id'
import type { LogicalGroup } from '../../api/types'
import { findPairedZones, PUBLIC_ZONE_SEMANTIC_ROLE, slugifyZoneName, STAFF_ZONE_SEMANTIC_ROLE, zoneResourceLabel } from './zones'
import type { PolicyTarget } from './catalog'

function group(overrides: Partial<LogicalGroup> = {}): LogicalGroup {
  return { id: 'g1', guild_id: discordSnowflake('1'), name: 'Direction', slug: 'direction-abc', description: null, resources: [], ...overrides }
}

describe('findPairedZones', () => {
  it('recognises a group with both a public and a staff tagged resource', () => {
    const groups = [group({
      resources: [
        { resource_type: 'CATEGORY', discord_channel_id: discordSnowflake('10'), semantic_role: PUBLIC_ZONE_SEMANTIC_ROLE },
        { resource_type: 'CATEGORY', discord_channel_id: discordSnowflake('11'), semantic_role: STAFF_ZONE_SEMANTIC_ROLE },
      ],
    })]
    const paired = findPairedZones(groups)
    expect(paired).toHaveLength(1)
    expect(paired[0]?.publicResource.discord_channel_id).toBe('10')
    expect(paired[0]?.staffResource.discord_channel_id).toBe('11')
  })

  it('ignores a group missing one side of the pairing', () => {
    const groups = [group({ resources: [{ resource_type: 'CATEGORY', discord_channel_id: discordSnowflake('10'), semantic_role: PUBLIC_ZONE_SEMANTIC_ROLE }] })]
    expect(findPairedZones(groups)).toHaveLength(0)
  })

  it('ignores unrelated logical groups with no zone tagging', () => {
    const groups = [group({ resources: [{ resource_type: 'CATEGORY', discord_channel_id: discordSnowflake('10'), semantic_role: null }] })]
    expect(findPairedZones(groups)).toHaveLength(0)
  })
})

describe('slugifyZoneName', () => {
  it('produces a lowercase, kebab-case slug with a unique suffix', () => {
    const slug = slugifyZoneName('Direction publique + Staff')
    expect(slug).toMatch(/^[a-z0-9]+(?:-[a-z0-9]+)*$/)
    expect(slug.startsWith('direction-publique-staff-')).toBe(true)
  })

  it('falls back to a generic base when the name has no ASCII letters', () => {
    expect(slugifyZoneName('★★★')).toMatch(/^zone-[a-z0-9]+$/)
  })
})

describe('zoneResourceLabel', () => {
  const targets: PolicyTarget[] = [{ kind: 'CATEGORY', scopeType: 'CATEGORY', scopeId: '10', label: 'Direction' }]

  it('resolves the human label from the current target list', () => {
    const label = zoneResourceLabel({ resource_type: 'CATEGORY', discord_channel_id: discordSnowflake('10'), semantic_role: PUBLIC_ZONE_SEMANTIC_ROLE }, targets)
    expect(label).toBe('Direction')
  })

  it('returns the raw id when the resource no longer resolves to a known target', () => {
    const label = zoneResourceLabel({ resource_type: 'CATEGORY', discord_channel_id: discordSnowflake('999'), semantic_role: PUBLIC_ZONE_SEMANTIC_ROLE }, targets)
    expect(label).toBe('999')
  })

  it('returns null when there is no resource at all', () => {
    expect(zoneResourceLabel(undefined, targets)).toBeNull()
  })

  it('never falls back to the GUILD target (scopeId null) when the resource id is missing', () => {
    const targetsWithGuild: PolicyTarget[] = [{ kind: 'GUILD', scopeType: 'GUILD', scopeId: null, label: 'Guild A' }, ...targets]
    const label = zoneResourceLabel({ resource_type: 'CATEGORY', semantic_role: PUBLIC_ZONE_SEMANTIC_ROLE }, targetsWithGuild)
    expect(label).toBeNull()
  })
})
