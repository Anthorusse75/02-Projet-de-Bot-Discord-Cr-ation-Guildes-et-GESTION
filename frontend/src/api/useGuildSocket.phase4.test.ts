import { resolveGuildEvent } from './useGuildSocket'

describe('Phase 4 live access reconciliation', () => {
  it('routes Discord role events to the roles read model without disturbing structure events', () => {
    const guild = '700000000000000001'
    expect(resolveGuildEvent({ guild_id: guild, sequence: 2, version: 1, type: 'GUILD_ROLE_UPDATE' }, guild, 1)).toMatchObject({ kind: 'feature', feature: 'roles', nextSequence: 2 })
    expect(resolveGuildEvent({ guild_id: guild, sequence: 3, version: 1, type: 'role.updated' }, guild, 2)).toMatchObject({ kind: 'feature', feature: 'roles', nextSequence: 3 })
    expect(resolveGuildEvent({ guild_id: guild, sequence: 4, version: 1, type: 'CHANNEL_UPDATE' }, guild, 3)).toMatchObject({ kind: 'feature', feature: 'structure', nextSequence: 4 })
  })
})
