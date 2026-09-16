import type { Role, VisibilityScope } from '../../api/types'
import { discordSnowflake } from '../../shared/discord-id'
import { CONFIRMED_MEMBER_SCOPE_KEY, findNamedAudience, STAFF_SCOPE_KEY, suggestStaffRoleIds } from './audiences'

function scope(overrides: Partial<VisibilityScope>): VisibilityScope {
  return {
    id: 'scope-1', guild_id: discordSnowflake('700000000000000001'), scope_type: 'STAFF', scope_key: STAFF_SCOPE_KEY,
    name: 'Staff', logical_group_id: null, config: {}, version: 1, rules: [], explicit_member_ids: [],
    ...overrides,
  }
}

describe('Named Audience definitions (REQ-AP-ZONE-010/020)', () => {
  it('finds the Staff scope by scope_type=STAFF, never by role name', () => {
    const scopes = [scope({ rules: [{ rule_type: 'ANY_DISCORD_ROLE', config: { role_ids: [discordSnowflake('1'), discordSnowflake('2')] }, priority: 0 }] })]
    const audience = findNamedAudience(scopes, 'STAFF')
    expect(audience?.roleIds).toEqual(['1', '2'])
  })

  it('finds the Confirmed-member scope as CUSTOM + a well-known scope_key, not a new table', () => {
    const scopes = [scope({
      scope_type: 'CUSTOM', scope_key: CONFIRMED_MEMBER_SCOPE_KEY, name: 'Confirmed member',
      rules: [{ rule_type: 'ANY_DISCORD_ROLE', config: { role_ids: [discordSnowflake('9')] }, priority: 0 }],
    })]
    expect(findNamedAudience(scopes, 'CONFIRMED_MEMBER')?.roleIds).toEqual(['9'])
    expect(findNamedAudience(scopes, 'STAFF')).toBeNull()
  })

  it('returns null (never invents an audience) when no definition is persisted yet', () => {
    expect(findNamedAudience([], 'STAFF')).toBeNull()
    expect(findNamedAudience([], 'CONFIRMED_MEMBER')).toBeNull()
  })

  it('ignores an unrelated CUSTOM scope that does not use the confirmed_member key', () => {
    const scopes = [scope({ scope_type: 'CUSTOM', scope_key: 'some-other-scope', rules: [{ rule_type: 'ANY_DISCORD_ROLE', config: { role_ids: [discordSnowflake('5')] }, priority: 0 }] })]
    expect(findNamedAudience(scopes, 'CONFIRMED_MEMBER')).toBeNull()
  })

  it('suggests staff roles from name hints only as a proposal, never as a decision', () => {
    const roles: Role[] = [
      { id: discordSnowflake('1'), name: 'Administrateur', position: 3, permissions: '0', known_flags: [], unknown_bits: '0', managed: false, freshness: 'FRESH' },
      { id: discordSnowflake('2'), name: 'Modérateur', position: 2, permissions: '0', known_flags: [], unknown_bits: '0', managed: false, freshness: 'FRESH' },
      { id: discordSnowflake('3'), name: 'Membre', position: 1, permissions: '0', known_flags: [], unknown_bits: '0', managed: false, freshness: 'FRESH' },
    ]
    const suggestion = suggestStaffRoleIds(roles)
    expect(suggestion).toEqual(['1', '2'])
    // The suggestion is a plain array the caller must explicitly confirm and save
    // through useSaveNamedAudience -- it is never written on its own here.
  })
})
