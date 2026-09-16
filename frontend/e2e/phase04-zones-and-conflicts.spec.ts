import { expect, test, type Page } from '@playwright/test'

const USER = '700000000000000003'
const GUILD = '700000000000000001'
const STAFF_ROLE = '700000000000000011'
const VERIFIED_ROLE = '700000000000000012'
const CONTRACTORS_ROLE = '700000000000000013'
const MANAGERS_ROLE = '700000000000000014'
const CAT = '700000000000000101'
const CHANNEL = '700000000000000201'
const MEMBER = '700000000000000301'
const POLICY_DRAFT = '11111111-1111-4111-8111-111111111111'
const POLICY_BLACKLIST = '22222222-2222-4222-8222-222222222222'
const POLICY_REGRANT = '33333333-3333-4333-8333-333333333333'
const STAFF_SCOPE_ID = '44444444-4444-4444-8444-444444444444'
const CONFIRMED_SCOPE_ID = '55555555-5555-4555-8555-555555555555'

type Scope = { id: string; guild_id: string; scope_type: string; scope_key: string; name: string; logical_group_id: null; config: Record<string, unknown>; version: number; rules: Record<string, unknown>[]; explicit_member_ids: string[] }
type Harness = {
  policies: Record<string, unknown>[]
  scopes: Scope[]
  requests: Array<{ path: string; method: string; body: unknown }>
  resolutionCallCount: number
  blacklist?: boolean
}

const can = () => ({ outcome: 'CAN', causes: [], remediations: [] })
function capabilities() {
  return { guild_id: GUILD, source: 'AUTHORIZATION_AND_LOCAL_CACHE', discord_rest_calls: 0,
    user_capabilities: { 'tenant.read': can(), 'policies.read': can(), 'policies.create': can(), 'policies.update': can(), 'policies.activate': can(), 'plans.create': can() },
    scoped_capabilities: { scope_kind: 'GUILD', scope_id: '*', capabilities: {} }, bot_operations: {}, coverage: 'FULL', completeness: 'FULL', freshness: 'FRESH' }
}
function roles() {
  return { guild_id: GUILD, source: 'LOCAL_CACHE', discord_rest_calls: 0, roles: [
    { id: STAFF_ROLE, name: 'Administrators', position: 6, permissions: '0', known_flags: [], unknown_bits: '0', managed: false, freshness: 'FRESH' },
    { id: VERIFIED_ROLE, name: 'Verified', position: 5, permissions: '0', known_flags: [], unknown_bits: '0', managed: false, freshness: 'FRESH' },
    { id: CONTRACTORS_ROLE, name: 'Contractors', position: 4, permissions: '0', known_flags: [], unknown_bits: '0', managed: false, freshness: 'FRESH' },
    { id: MANAGERS_ROLE, name: 'Managers', position: 3, permissions: '0', known_flags: [], unknown_bits: '0', managed: false, freshness: 'FRESH' },
  ] }
}
function structure() {
  const base = { guild_id: GUILD, position: 0, resource_kind: 'CHANNEL', observability: 'VISIBLE', freshness: 'FRESH', data_assertion: 'CURRENT_CONFIRMED', threads: [] }
  return { guild_id: GUILD, source: 'LOCAL_CACHE', discord_rest_calls: 0, categories: [{ ...base, id: CAT, type: 4, name: 'General', parent_id: null, channels: [{ ...base, id: CHANNEL, type: 0, name: 'board', parent_id: CAT }] }], root_channels: [] }
}
function scope(overrides: Partial<Scope>): Scope {
  return { id: STAFF_SCOPE_ID, guild_id: GUILD, scope_type: 'STAFF', scope_key: 'staff', name: 'Staff', logical_group_id: null, config: {}, version: 1, rules: [], explicit_member_ids: [], ...overrides }
}
function draftPolicy(overrides: Record<string, unknown> = {}) {
  return { policy_id: POLICY_DRAFT, guild_id: GUILD, policy_type: 'ACCESS_CONTROL', contract_version: 1, name: 'Board access', description: 'Managers only', lifecycle_state: 'DRAFT', revision: 1, priority: 0, scope_type: 'CHANNEL', scope_id: CHANNEL, conditions: [{ kind: 'ROLE_MATCH', match: 'ANY', role_ids: [STAFF_ROLE] }], effects: [{ kind: 'SET_ACCESS', access: 'VIEW', decision: 'ALLOW' }], metadata: { summary: 'Managers only', tags: ['did-native:visible_only'], reason: null }, created_by_user_id: USER, modified_by_user_id: USER, created_at: '2026-09-15T08:00:00Z', updated_at: '2026-09-15T08:00:00Z', activated_at: null, disabled_at: null, retired_at: null, ...overrides }
}
function resolution(outcome: 'CAN' | 'CANNOT', extra: Record<string, unknown> = {}) {
  return { guild_id: GUILD, subject_id: MEMBER, decision: 'ACCESS_CONTROL:VIEW', outcome, target_scope_type: 'CHANNEL', target_scope_id: CHANNEL, target_state: 'CURRENT', target_freshness: 'FRESH', coverage: 'FULL', applicable_policies: [], contributions: [], conflicts: [], source_scopes: [], priority_trace: [], conditions: [], incomplete_reasons: [], warnings: [], source_versions: ['cache-v1'], discord_permissions: outcome === 'CAN' ? ['VIEW_CHANNEL'] : [], discord_allow_bits: outcome === 'CAN' ? '1024' : '0', discord_deny_bits: outcome === 'CAN' ? '0' : '1024', discord_translation_diagnostics: [], conflict_explanations: [], blacklist_regrants: [], ...extra }
}
function previewFor(policyId: string) {
  return { policy_id: policyId, policy_revision: 1, lifecycle_state: 'DRAFT', scope_type: 'CHANNEL', scope_id: CHANNEL,
    entries: [{ target: { subject_id: MEMBER, scope_type: 'CHANNEL', scope_id: CHANNEL, requested_access: 'VIEW' }, current: resolution('CANNOT'), proposed: resolution('CAN'), access_change: 'GAINED', gained_contributions: ['new'], lost_contributions: [], conflicts_created: [], conflicts_resolved: [], diagnostics: [], warnings: [], remediations: [] }],
    impact: { accuracy: 'EXACT', candidate_contexts: 1, evaluated_contexts: 1, affected_resources: 1, affected_roles: 1, affected_members: 1, access_gains: 1, access_losses: 0, conflicts: 0, impossible_or_incomplete_targets: 0, lower_bound_only: false, diagnostics: [] },
    freshness: 'FRESH', coverage: 'FULL', source_versions: ['cache-v1'], warnings: [], persisted: false, discord_mutations: 0 }
}

async function install(page: Page, harness: Harness) {
  await page.route('**/health/features', (route) => route.fulfill({ json: { features: { oauth: true, live_events: true, portability: true } } }))
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request(); const path = new URL(request.url()).pathname; const method = request.method(); const body = request.postDataJSON() ?? null
    if (!['GET', 'HEAD'].includes(method)) harness.requests.push({ path, method, body })
    if (path === '/api/v1/ui/locales') return route.fulfill({ json: { catalog_version: 'did-ui-v2', locales: [] } })
    if (path.startsWith('/api/v1/ui/locales/')) return route.fulfill({ status: 404, json: {} })
    if (path === '/api/v1/me') return route.fulfill({ json: { authenticated: true, user: { discord_user_id: USER, username: 'owner', global_name: 'Owner' }, active_guild_id: GUILD, csrf_token: 'csrf', policy_version: 1 } })
    if (path === '/api/v1/me/preferences') return route.fulfill({ json: { ui_locale_override_code: 'en', timezone: null } })
    if (path === '/api/v1/guilds') return route.fulfill({ json: { guilds: [{ guild_id: GUILD, name: 'Guild A', owner: true, permissions: '8', installation_status: 'ACTIVE' }] } })
    if (path.endsWith('/dashboard-capabilities')) return route.fulfill({ json: capabilities() })
    if (path.endsWith('/roles')) return route.fulfill({ json: roles() })
    if (path.endsWith('/structure')) return route.fulfill({ json: structure() })
    if (path.endsWith('/logical-groups')) return route.fulfill({ json: { guild_id: GUILD, groups: [] } })
    if (path.endsWith('/visibility-scopes') && method === 'GET') return route.fulfill({ json: { guild_id: GUILD, scopes: harness.scopes } })
    if (path.endsWith('/visibility-scopes') && method === 'POST') {
      const input = body as Record<string, unknown>
      const created: Scope = { id: input.scope_type === 'STAFF' ? STAFF_SCOPE_ID : CONFIRMED_SCOPE_ID, guild_id: GUILD, scope_type: String(input.scope_type), scope_key: String(input.scope_key), name: String(input.name), logical_group_id: null, config: {}, version: 1, rules: input.rules as Record<string, unknown>[], explicit_member_ids: [] }
      harness.scopes.push(created)
      return route.fulfill({ status: 201, json: { guild_id: GUILD, id: created.id } })
    }
    if (/\/visibility-scopes\/[^/]+$/.test(path) && method === 'PATCH') {
      const input = body as Record<string, unknown>
      const target = harness.scopes.find((item) => path.endsWith(item.id))
      if (target) { target.rules = input.rules as Record<string, unknown>[]; target.version += 1 }
      return route.fulfill({ status: 204, json: {} })
    }
    if (path.endsWith('/policies') && method === 'GET') return route.fulfill({ json: { guild_id: GUILD, policies: harness.policies } })
    if (path.endsWith('/policies') && method === 'POST') {
      const created = draftPolicy({ ...(body as Record<string, unknown>), policy_id: POLICY_DRAFT })
      harness.policies.push(created)
      return route.fulfill({ status: 201, json: created })
    }
    if (/\/policies\/[^/]+\/preview$/.test(path)) return route.fulfill({ json: previewFor(POLICY_DRAFT) })
    if (path.endsWith(`/policies/${POLICY_DRAFT}/versions`)) return route.fulfill({ json: { guild_id: GUILD, policy_id: POLICY_DRAFT, versions: [] } })
    if (path.endsWith('/policy-resolution')) {
      harness.resolutionCallCount += 1
      if (harness.blacklist) {
        return route.fulfill({ json: resolution('CAN', {
          blacklist_regrants: [{ excluding_policy_id: POLICY_BLACKLIST, excluding_role_ids: [CONTRACTORS_ROLE], regranting_policy_id: POLICY_REGRANT, regranting_role_ids: [{ role_id: MANAGERS_ROLE, source_policy_id: POLICY_REGRANT, source: 'AUDIENCE_INCLUDE' }], accepted: false, reason_key: 'policy.conflict.blacklist_bypassed_by_role' }],
        }) })
      }
      // First check: member not yet confirmed -> CANNOT. Re-checking later reflects the live facts changing (member gained the role), not a frozen snapshot.
      return route.fulfill({ json: resolution(harness.resolutionCallCount >= 2 ? 'CAN' : 'CANNOT') })
    }
    if (/\/policies\/[^/]+\/accept-exception$/.test(path)) {
      return route.fulfill({ json: draftPolicy({ policy_id: POLICY_BLACKLIST, lifecycle_state: 'ACTIVE', revision: 2, metadata: { summary: 'Blacklist', tags: [`exception_accepted:${POLICY_REGRANT}`], reason: null } }) })
    }
    if (/\/policies\/[^/]+\/plan$/.test(path)) return route.fulfill({ status: 201, json: { created: true, preview: previewFor(POLICY_DRAFT), plan: { id: '66666666-6666-4666-8666-666666666666', status: 'VALIDATED', state_version: 2 }, preflight: { allowed: true, errors: [], warnings: [] } } })
    if (path.endsWith('/plans')) return route.fulfill({ json: { guild_id: GUILD, plans: [] } })
    return route.fulfill({ status: 404, json: {} })
  })
}

test('@a11y A: Staff only reuses the persisted Staff definition end to end through Preview -> Plan, zero APPLY', async ({ page }) => {
  const harness: Harness = { policies: [], scopes: [], requests: [], resolutionCallCount: 0 }
  await install(page, harness)
  await page.goto(`/guild/${GUILD}/policies`)
  await page.getByLabel('Target resource').selectOption(`TEXT_CHANNEL:${CHANNEL}`)
  await page.getByRole('button', { name: /Staff only/ }).click()
  await expect(page.getByText('Staff configuration required')).toBeVisible()
  // DID may propose a detection from role names, but never applies it silently:
  // it stays an unconfirmed suggestion until the admin opens the editor and saves.
  await expect(page.getByText(/Suggestion: Administrators/)).toBeVisible()
  await page.getByRole('button', { name: 'Configure' }).click()
  await expect(page.getByRole('group', { name: 'Roles and audiences' }).getByLabel('Administrators')).toBeChecked()
  await page.getByRole('button', { name: 'Save this definition' }).click()
  await expect(page.getByText('Staff = Administrators')).toBeVisible()
  expect(harness.requests.some((item) => item.path.endsWith('/visibility-scopes') && item.method === 'POST')).toBe(true)
  await page.getByLabel('Policy name').fill('Staff space')
  await page.getByRole('button', { name: 'Create draft' }).click()
  await expect(page.getByText('Draft created. Discord was not changed.')).toBeVisible()
  await page.getByRole('button', { name: 'Preview impact' }).click()
  await expect(page.getByText('Exact impact')).toBeVisible()
  await page.getByRole('button', { name: 'Prepare plan' }).click()
  await expect(page).toHaveURL(new RegExp(`/guild/${GUILD}/plans$`))
  expect(harness.requests.some((item) => /apply/i.test(item.path))).toBe(false)
})

test('B: Confirmed members only is defined once, then re-evaluated live (not from a frozen snapshot)', async ({ page }) => {
  const harness: Harness = { policies: [], scopes: [], requests: [], resolutionCallCount: 0 }
  await install(page, harness)
  await page.goto(`/guild/${GUILD}/policies`)
  await page.getByLabel('Target resource').selectOption(`TEXT_CHANNEL:${CHANNEL}`)
  await page.getByRole('button', { name: /Confirmed members only/ }).click()
  await expect(page.getByText('Confirmed-member configuration required')).toBeVisible()
  await page.getByRole('button', { name: 'Configure' }).click()
  await page.getByRole('group', { name: 'Roles and audiences' }).getByText('Verified').click()
  await page.getByRole('button', { name: 'Save this definition' }).click()
  await expect(page.getByText('Confirmed = Verified')).toBeVisible()
  await page.getByLabel('Policy name').fill('Confirmed area')
  await page.getByRole('button', { name: 'Create draft' }).click()
  await page.getByRole('button', { name: 'Preview impact' }).click()
  const explainPanel = page.locator('.policy-explain-panel')
  await page.getByRole('button', { name: 'Why this result?' }).click()
  await expect(explainPanel.getByText('Denied', { exact: true })).toBeVisible()
  // The member gains the Verified role between the two checks; DID must re-evaluate from
  // current facts, not replay the first answer (REQ-AP-ZONE-031/032).
  await page.getByRole('button', { name: 'Why this result?' }).click()
  await expect(explainPanel.getByText('Allowed', { exact: true })).toBeVisible()
  expect(harness.resolutionCallCount).toBeGreaterThanOrEqual(2)
})

test('C: a blacklist bypass names the exact regranting role and can become a documented exception, zero APPLY', async ({ page }) => {
  const harness: Harness = {
    policies: [
      draftPolicy(),
      draftPolicy({ policy_id: POLICY_BLACKLIST, name: 'Visible except Contractors', lifecycle_state: 'ACTIVE', conditions: [{ kind: 'ALWAYS' }], effects: [{ kind: 'SET_ACCESS', access: 'VIEW', decision: 'ALLOW', audience: { mode: 'EXCLUDE', match: 'ANY', role_ids: [CONTRACTORS_ROLE] } }] }),
      draftPolicy({ policy_id: POLICY_REGRANT, name: 'Managers always see', lifecycle_state: 'ACTIVE', conditions: [{ kind: 'ALWAYS' }], effects: [{ kind: 'SET_ACCESS', access: 'VIEW', decision: 'ALLOW', audience: { mode: 'INCLUDE', match: 'ANY', role_ids: [MANAGERS_ROLE] } }] }),
    ],
    scopes: [], requests: [], resolutionCallCount: 0, blacklist: true,
  }
  await install(page, harness)
  await page.goto(`/guild/${GUILD}/policies`)
  await page.getByLabel('Target resource').selectOption(`TEXT_CHANNEL:${CHANNEL}`)
  await page.getByRole('button', { name: /Board access/ }).click()
  await page.getByRole('button', { name: 'Preview impact' }).click()
  await page.getByRole('button', { name: 'Why this result?' }).click()
  await expect(page.getByText(/still has access through Managers/)).toBeVisible()
  await expect(page.getByText(/Visible except Contractors excludes this member because of Contractors/)).toBeVisible()
  await expect(page.getByText(/Managers always see independently grants access back/)).toBeVisible()
  await page.getByRole('button', { name: 'Accept this exception' }).click()
  await expect(page.getByText('Exception documented. It will no longer show as a silent conflict.')).toBeVisible()
  expect(harness.requests.some((item) => item.path.endsWith('/accept-exception'))).toBe(true)
  expect(harness.requests.some((item) => /apply/i.test(item.path))).toBe(false)
})
