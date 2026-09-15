import type { Policy } from '../../api/types'
import { phase4PoliciesPacks } from '../../localization/phase4PoliciesCatalog'
import { clonePolicyDefinition, compatibleNativePolicies, createDefinitionFromNative, nativePolicies, type PolicyTarget } from './catalog'

const target: PolicyTarget = { kind: 'TEXT_CHANNEL', scopeType: 'CHANNEL', scopeId: '700000000000000201', label: 'welcome' }

describe('Phase 4 access policy catalogue', () => {
  it('ships the seven required native intentions and filters incompatible voice policies', () => {
    expect(nativePolicies.map((policy) => policy.id)).toEqual([
      'visible_only', 'visible_except', 'write_only', 'write_except', 'open_read_limited_write', 'private_space', 'staff_only',
    ])
    expect(compatibleNativePolicies('VOICE_CHANNEL').map((policy) => policy.id)).toEqual(['staff_only'])
    expect(compatibleNativePolicies('ROLE')).toEqual([])
    expect(compatibleNativePolicies('TEXT_CHANNEL')).toHaveLength(7)
  })

  it('compiles simple human input to one canonical ACCESS_CONTROL v1 definition', () => {
    const native = nativePolicies[0]
    if (!native) throw new Error('required native policy missing')
    const definition = createDefinitionFromNative(native, target, ['700000000000000011', '700000000000000012'], { name: 'Direction', description: 'Managers only' })
    expect(definition).toMatchObject({
      policy_type: 'ACCESS_CONTROL', contract_version: 1, scope_type: 'CHANNEL', scope_id: target.scopeId,
      conditions: [{ kind: 'ALWAYS' }],
      effects: [{ kind: 'SET_ACCESS', access: 'VIEW', decision: 'ALLOW', audience: { mode: 'INCLUDE', match: 'ANY', role_ids: ['700000000000000011', '700000000000000012'] } }],
      metadata: { tags: ['did-native:visible_only', 'audience:include'] },
    })
  })

  it('keeps open reading separate from limited publishing and encodes exclusions server-side', () => {
    const openRead = nativePolicies.find((policy) => policy.id === 'open_read_limited_write')
    const blacklist = nativePolicies.find((policy) => policy.id === 'visible_except')
    if (!openRead || !blacklist) throw new Error('required native policy missing')
    const openDefinition = createDefinitionFromNative(openRead, target, ['700000000000000011'], { name: 'Announcements', description: 'Readers and publishers' })
    expect(openDefinition.effects).toEqual([
      { kind: 'SET_ACCESS', access: 'VIEW', decision: 'ALLOW' },
      { kind: 'SET_ACCESS', access: 'WRITE', decision: 'ALLOW', audience: { mode: 'INCLUDE', match: 'ANY', role_ids: ['700000000000000011'] } },
    ])
    expect(createDefinitionFromNative(blacklist, target, ['700000000000000012'], { name: 'Exclude guests', description: 'Guest exclusion' }).effects[0]).toMatchObject({
      decision: 'ALLOW', audience: { mode: 'EXCLUDE', role_ids: ['700000000000000012'] },
    })
  })

  it('duplicates an existing revision as a distinct draft definition without changing its model', () => {
    const policy = {
      policy_id: '11111111-1111-4111-8111-111111111111', guild_id: '700000000000000001', policy_type: 'ACCESS_CONTROL', contract_version: 1,
      name: 'Direction', description: 'Managers only', lifecycle_state: 'ACTIVE', revision: 4, priority: 10, scope_type: 'CHANNEL', scope_id: target.scopeId,
      conditions: [{ kind: 'ROLE_MATCH', match: 'ANY', role_ids: ['700000000000000011'] }], effects: [{ kind: 'SET_ACCESS', access: 'VIEW', decision: 'ALLOW' }],
      metadata: { summary: 'Managers only', tags: ['did-native:visible_only'], reason: null }, created_by_user_id: '700000000000000003', modified_by_user_id: '700000000000000003',
      created_at: null, updated_at: null, activated_at: null, disabled_at: null, retired_at: null,
    } as Policy
    const duplicate = clonePolicyDefinition(policy, 'Direction v2')
    expect(duplicate.conditions).toEqual(policy.conditions)
    expect(duplicate.effects).toEqual(policy.effects)
    expect(duplicate.metadata.tags).toContain(`source-policy:${policy.policy_id}`)
  })

  it('keeps the Phase 4 policy catalogue structurally complete in EN/FR/DE/ES', () => {
    const keys = Object.keys(phase4PoliciesPacks.en).sort()
    for (const pack of Object.values(phase4PoliciesPacks)) expect(Object.keys(pack).sort()).toEqual(keys)
    expect(phase4PoliciesPacks.fr['nav.policies']).toBe('Politiques d’accès')
    expect(phase4PoliciesPacks.de['nav.policies']).not.toBe(phase4PoliciesPacks.en['nav.policies'])
    expect(phase4PoliciesPacks.es['nav.policies']).not.toBe(phase4PoliciesPacks.en['nav.policies'])
  })
})
