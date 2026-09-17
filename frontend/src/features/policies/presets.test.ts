import { describe, expect, it } from 'vitest'
import type { PolicyTarget } from './catalog'
import {
  announcementSubRules, confidentialSubRules, createAnnouncementDefinitions, createConfidentialDefinitions,
  createSupportZoneDefinitions, emptyAnnouncementConfig, emptyConfidentialConfig, emptySupportZoneConfig,
  supportZoneSubRules,
} from './presets'

const target: PolicyTarget = { kind: 'CATEGORY', scopeType: 'CATEGORY', scopeId: '10', label: 'Direction' }

describe('confidential preset', () => {
  it('activates only the sub-rules backed by real configuration', () => {
    const rules = confidentialSubRules({ ...emptyConfidentialConfig(), viewerRoleIds: ['1'] })
    expect(rules.map((rule) => rule.key)).toEqual(['visibility', 'mentions'])
  })

  it('activates the threads sub-rule once a manager audience exists', () => {
    const rules = confidentialSubRules({ ...emptyConfidentialConfig(), viewerRoleIds: ['1'], managerRoleIds: ['2'] })
    expect(rules.map((rule) => rule.key)).toEqual(['visibility', 'management', 'mentions', 'threads'])
  })

  it('never activates the threads sub-rule without a manager audience, even if restrictThreads is on', () => {
    const rules = confidentialSubRules({ ...emptyConfidentialConfig(), managerRoleIds: [] })
    expect(rules.some((rule) => rule.key === 'threads')).toBe(false)
  })

  it('creates one DRAFT Policy per activated sub-rule, sharing one preset group tag', () => {
    const definitions = createConfidentialDefinitions(target, 'Direction', 'Board only', {
      viewerRoleIds: ['1', '2'], managerRoleIds: ['1'], blockMentions: true, restrictThreads: true,
    })
    expect(definitions).toHaveLength(4)
    const groupTags = new Set(definitions.map((definition) => definition.metadata.tags.find((tag) => tag.startsWith('preset-group:'))))
    expect(groupTags.size).toBe(1)
    expect(definitions.every((definition) => definition.metadata.tags.includes('did-preset:confidential'))).toBe(true)
    expect(definitions.every((definition) => definition.scope_type === 'CATEGORY' && definition.scope_id === '10')).toBe(true)
    const mentionRule = definitions.find((definition) => definition.metadata.tags.includes('preset-part:mentions'))
    expect(mentionRule?.effects).toEqual([{ kind: 'SET_ACCESS', access: 'MENTION_EVERYONE_HERE', decision: 'DENY' }])
  })

  it('creates nothing when every sub-rule is explicitly turned off', () => {
    const nothingConfig = { viewerRoleIds: [], managerRoleIds: [], blockMentions: false, restrictThreads: false }
    expect(createConfidentialDefinitions(target, 'Direction', '', nothingConfig)).toHaveLength(0)
  })

  it('the default config still blocks mentions -- the one sub-rule that needs no audience to be meaningful', () => {
    expect(createConfidentialDefinitions(target, 'Direction', '', emptyConfidentialConfig())).toHaveLength(1)
  })
})

describe('announcement channel preset', () => {
  it('never touches visibility -- only writer/reaction/thread sub-rules exist', () => {
    const definitions = createAnnouncementDefinitions(target, 'News', '', { publisherRoleIds: ['1'], reactionMode: 'ONLY', threadMode: 'NONE' })
    expect(definitions.every((definition) => !definition.effects.some((effect) => effect.access === 'VIEW'))).toBe(true)
  })

  it('leaves reactions/threads untouched (INHERIT) when not configured (REQ-AP-PRS-013 is optional)', () => {
    const rules = announcementSubRules(emptyAnnouncementConfig())
    expect(rules).toHaveLength(0)
    expect(createAnnouncementDefinitions(target, 'News', '', emptyAnnouncementConfig())).toHaveLength(0)
  })

  it('creates a writers whitelist policy when publishers are chosen', () => {
    const definitions = createAnnouncementDefinitions(target, 'News', '', { ...emptyAnnouncementConfig(), publisherRoleIds: ['9'] })
    expect(definitions).toHaveLength(1)
    expect(definitions[0]?.effects[0]).toMatchObject({ kind: 'SET_ACCESS', access: 'WRITE', decision: 'ALLOW' })
  })
})

describe('support zone preset', () => {
  it('defaults to open visibility and open writing, both stated explicitly', () => {
    const rules = supportZoneSubRules(emptySupportZoneConfig())
    expect(rules.map((rule) => rule.key)).toEqual(['visibility', 'write'])
    expect(rules[0]?.labelKey).toBe('policies.preset.supportZone.rule.visibilityOpen')
    expect(rules[1]?.labelKey).toBe('policies.preset.supportZone.rule.writeEveryone')
  })

  it('creates a visibility whitelist only when explicitly set to PRIVATE with a real support audience', () => {
    const definitions = createSupportZoneDefinitions(target, 'Support', '', { supportRoleIds: ['5'], visibility: 'PRIVATE', writeMode: 'SUPPORT_ONLY' })
    expect(definitions).toHaveLength(2)
  })

  it('creates nothing for the default open/open configuration (nothing to restrict)', () => {
    expect(createSupportZoneDefinitions(target, 'Support', '', emptySupportZoneConfig())).toHaveLength(0)
  })
})
