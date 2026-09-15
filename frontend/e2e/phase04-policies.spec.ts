import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

const USER = '700000000000000003'
const GUILD = '700000000000000001'
const ROLE = '700000000000000011'
const OTHER_ROLE = '700000000000000012'
const CAT = '700000000000000101'
const CHANNEL = '700000000000000201'
const MEMBER = '700000000000000301'
const POLICY = '11111111-1111-4111-8111-111111111111'

type Harness = { policies: Record<string, unknown>[]; requests: Array<{path:string;method:string;body:unknown}>; conflict?: boolean; denied?: boolean }
const can = () => ({ outcome: 'CAN', causes: [], remediations: [] })

function capabilities(denied = false) {
  const userCapabilities: Record<string, ReturnType<typeof can>> = { 'tenant.read': can(), 'policies.create': can(), 'policies.update': can(), 'policies.activate': can(), 'plans.create': can() }
  if (!denied) userCapabilities['policies.read'] = can()
  return { guild_id: GUILD, source: 'AUTHORIZATION_AND_LOCAL_CACHE', discord_rest_calls: 0,
    user_capabilities: userCapabilities,
    scoped_capabilities: { scope_kind: 'GUILD', scope_id: '*', capabilities: {} }, bot_operations: {}, coverage: 'FULL', completeness: 'FULL', freshness: 'FRESH' }
}

function roles() { return { guild_id: GUILD, source: 'LOCAL_CACHE', discord_rest_calls: 0, roles: [
  { id: ROLE, name: 'Managers', position: 5, permissions: '0', known_flags: [], unknown_bits: '0', managed: false, freshness: 'FRESH' },
  { id: OTHER_ROLE, name: 'Guests', position: 4, permissions: '0', known_flags: [], unknown_bits: '0', managed: false, freshness: 'FRESH' },
] } }

function structure() { const base = { guild_id: GUILD, position: 0, resource_kind: 'CHANNEL', observability: 'VISIBLE', freshness: 'FRESH', data_assertion: 'CURRENT_CONFIRMED', threads: [] }; return { guild_id: GUILD, source: 'LOCAL_CACHE', discord_rest_calls: 0, categories: [{ ...base, id: CAT, type: 4, name: 'Direction', parent_id: null, channels: [{ ...base, id: CHANNEL, type: 0, name: 'board', parent_id: CAT }] }], root_channels: [] } }

function policy(overrides: Record<string, unknown> = {}) { return { policy_id: POLICY, guild_id: GUILD, policy_type: 'ACCESS_CONTROL', contract_version: 1, name: 'Board access', description: 'Managers only', lifecycle_state: 'DRAFT', revision: 1, priority: 0, scope_type: 'CHANNEL', scope_id: CHANNEL, conditions: [{ kind: 'ROLE_MATCH', match: 'ANY', role_ids: [ROLE] }], effects: [{ kind: 'SET_ACCESS', access: 'VIEW', decision: 'ALLOW' }], metadata: { summary: 'Managers only', tags: ['did-native:visible_only', 'audience:include'], reason: null }, created_by_user_id: USER, modified_by_user_id: USER, created_at: '2026-09-15T08:00:00Z', updated_at: '2026-09-15T08:00:00Z', activated_at: null, disabled_at: null, retired_at: null, ...overrides } }

function resolution(outcome: 'CAN'|'CANNOT'|'BLOCKED'|'UNKNOWN', conflicts: Record<string, unknown>[] = []) { return { guild_id: GUILD, subject_id: MEMBER, decision: 'ACCESS_CONTROL:VIEW', outcome, target_scope_type: 'CHANNEL', target_scope_id: CHANNEL, target_state: 'CURRENT', target_freshness: 'FRESH', coverage: 'FULL', applicable_policies: [{ policy_id: POLICY, revision: 1, priority: 0, scope_type: 'CHANNEL', scope_id: CHANNEL, inherited: false, specificity: 3 }], contributions: [{ policy_id: POLICY, revision: 1, effect_index: 0, priority: 0, scope_type: 'CHANNEL', scope_id: CHANNEL, family: 'RESOURCE', specificity: 3, inherited: false, access: 'VIEW', decision: outcome === 'CAN' ? 'ALLOW' : 'DENY', condition_outcome: 'TRUE', selected: outcome === 'CAN' || outcome === 'CANNOT', disposition: outcome === 'BLOCKED' ? 'CONFLICT_UNRESOLVED' : 'SELECTED' }], conflicts, source_scopes: [{ policy_id: POLICY, revision: 1, scope_type: 'CHANNEL', scope_id: CHANNEL, family: 'RESOURCE', specificity: 3, inherited: false }], priority_trace: [], conditions: [], incomplete_reasons: outcome === 'UNKNOWN' ? ['policy.member_roles_incomplete'] : [], warnings: [], source_versions: ['cache-v1'] } }

function preview(conflict = false) {
  const blockedConflict = { policy_ids: [POLICY, '22222222-2222-4222-8222-222222222222'], revisions: [1, 2], source_scopes: [`CHANNEL:${CHANNEL}`, `ROLE:${OTHER_ROLE}`], effects: ['ALLOW VIEW', 'DENY VIEW'], resolution_rule: null, outcome: 'BLOCKED', winning_policy_ids: [] }
  const entries = conflict
    ? [{ target: { subject_id: MEMBER, scope_type: 'CHANNEL', scope_id: CHANNEL, requested_access: 'VIEW' }, current: resolution('CAN'), proposed: resolution('BLOCKED', [blockedConflict]), access_change: 'BLOCKED', gained_contributions: [], lost_contributions: [], conflicts_created: ['conflict'], conflicts_resolved: [], diagnostics: [], warnings: [], remediations: [] },
       { target: { subject_id: '700000000000000302', scope_type: 'CHANNEL', scope_id: CHANNEL, requested_access: 'VIEW' }, current: resolution('CANNOT'), proposed: resolution('UNKNOWN'), access_change: 'UNKNOWN', gained_contributions: [], lost_contributions: [], conflicts_created: [], conflicts_resolved: [], diagnostics: ['policy.member_roles_incomplete'], warnings: [], remediations: [] }]
    : [{ target: { subject_id: MEMBER, scope_type: 'CHANNEL', scope_id: CHANNEL, requested_access: 'VIEW' }, current: resolution('CANNOT'), proposed: resolution('CAN'), access_change: 'GAINED', gained_contributions: ['new'], lost_contributions: [], conflicts_created: [], conflicts_resolved: [], diagnostics: [], warnings: [], remediations: [] }]
  return { policy_id: POLICY, policy_revision: 1, lifecycle_state: 'DRAFT', scope_type: 'CHANNEL', scope_id: CHANNEL, entries, impact: { accuracy: 'EXACT', candidate_contexts: entries.length, evaluated_contexts: entries.length, affected_resources: 1, affected_roles: conflict ? 2 : 1, affected_members: entries.length, access_gains: conflict ? 0 : 1, access_losses: 0, conflicts: conflict ? 1 : 0, impossible_or_incomplete_targets: conflict ? 2 : 0, lower_bound_only: false, diagnostics: [] }, freshness: 'FRESH', coverage: 'FULL', source_versions: ['cache-v1'], warnings: [], persisted: false, discord_mutations: 0 }
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
    if (path.endsWith('/dashboard-capabilities')) return route.fulfill({ json: capabilities(harness.denied) })
    if (path.endsWith('/roles')) return route.fulfill({ json: roles() })
    if (path.endsWith('/structure')) return route.fulfill({ json: structure() })
    if (path.endsWith('/logical-groups')) return route.fulfill({ json: { guild_id: GUILD, groups: [] } })
    if (path.endsWith('/policies') && method === 'GET') return route.fulfill({ json: { guild_id: GUILD, policies: harness.policies } })
    if (path.endsWith('/policies') && method === 'POST') { const created = policy({ ...(body as Record<string, unknown>), policy_id: harness.policies.length ? '66666666-6666-4666-8666-666666666666' : POLICY }); harness.policies.push(created); return route.fulfill({ status: 201, json: created }) }
    if (path.endsWith(`/policies/${POLICY}/preview`)) return route.fulfill({ json: preview(Boolean(harness.conflict)) })
    if (path.endsWith(`/policies/${POLICY}/versions`)) return route.fulfill({ json: { guild_id: GUILD, policy_id: POLICY, versions: [{ version_id: '33333333-3333-4333-8333-333333333333', guild_id: GUILD, policy_id: POLICY, revision: 1, change_kind: 'CREATE', snapshot: policy(), author_user_id: USER, correlation_id: '44444444-4444-4444-8444-444444444444', idempotency_key: null, created_at: '2026-09-15T08:00:00Z' }] } })
    if (path.endsWith('/policy-resolution')) return route.fulfill({ json: resolution('CAN') })
    if (path.endsWith(`/policies/${POLICY}/plan`)) return route.fulfill({ status: 201, json: { created: true, preview: preview(), plan: { id: '55555555-5555-4555-8555-555555555555', status: 'VALIDATED', state_version: 2 }, preflight: { allowed: true, errors: [], warnings: [] } } })
    if (path.endsWith('/plans')) return route.fulfill({ json: { guild_id: GUILD, plans: [] } })
    return route.fulfill({ status: 404, json: {} })
  })
}

test('@a11y creates a DRAFT from a native human intention, previews canonically and prepares Policy→Plan without APPLY', async ({ page }) => {
  const harness: Harness = { policies: [], requests: [] }; await install(page, harness)
  await page.goto(`/guild/${GUILD}/policies`)
  await expect(page.getByRole('heading', { name: 'Access policies' })).toBeVisible()
  await page.getByLabel('Target resource').selectOption(`TEXT_CHANNEL:${CHANNEL}`)
  await page.getByRole('button', { name: /Visible only to/ }).click()
  await page.getByRole('group', { name: 'Roles and audiences' }).getByText('Managers').click()
  await page.getByRole('group', { name: 'Roles and audiences' }).getByText('Guests').click()
  await page.getByLabel('Policy name').fill('Board access')
  await page.getByRole('tab', { name: 'Expert mode' }).click()
  await expect(page.getByText(new RegExp(OTHER_ROLE))).toBeVisible()
  await page.getByRole('tab', { name: 'Simple mode' }).click()
  await expect(page.getByRole('group', { name: 'Roles and audiences' }).getByLabel('Guests')).toBeChecked()
  await page.getByRole('button', { name: 'Create draft' }).click()
  await expect(page.getByText('Draft created. Discord was not changed.')).toBeVisible()
  await page.getByRole('button', { name: 'Preview impact' }).click()
  await expect(page.getByText('Exact impact')).toBeVisible()
  await expect(page.getByText('Current: Denied · Proposed: Allowed')).toBeVisible()
  await page.getByRole('tab', { name: 'Expert mode' }).click()
  await expect(page.getByText(POLICY, { exact: true })).toBeVisible()
  await expect(page.getByText(/INCLUDE/)).toBeVisible()
  await expect(page.getByText(new RegExp(ROLE))).toBeVisible()
  const accessibility = await new AxeBuilder({ page }).include('#main').analyze()
  expect(accessibility.violations.filter((item) => ['serious', 'critical'].includes(item.impact ?? ''))).toEqual([])
  await page.getByRole('button', { name: 'Prepare plan' }).click()
  await expect(page).toHaveURL(new RegExp(`/guild/${GUILD}/plans$`))
  expect(harness.requests.some((item) => item.path.endsWith(`/policies/${POLICY}/plan`))).toBe(true)
  expect(harness.requests.some((item) => /apply/i.test(item.path))).toBe(false)
})

test('shows multi-role conflict causes, BLOCKED/UNKNOWN outcomes, explain and safe revision reuse', async ({ page }) => {
  const harness: Harness = { policies: [policy()], requests: [], conflict: true }; await install(page, harness)
  await page.goto(`/guild/${GUILD}/policies`)
  await page.getByLabel('Target resource').selectOption(`TEXT_CHANNEL:${CHANNEL}`)
  await page.getByRole('button', { name: /Board access/ }).click()
  await page.getByRole('button', { name: 'Preview impact' }).click()
  await expect(page.getByText('Blocked', { exact: true })).toBeVisible()
  await expect(page.getByText('Unknown', { exact: true })).toBeVisible()
  await expect(page.getByText(/Exception for member/)).toBeVisible()
  await page.getByRole('button', { name: 'Resolve this conflict' }).click()
  await expect(page.getByText('No member role is removed automatically.', { exact: false })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Prepare plan' })).toBeDisabled()
  await page.getByRole('button', { name: 'Why this result?' }).first().click()
  await expect(page.getByText('Why is this access allowed or denied?')).toBeVisible()
  await page.getByRole('button', { name: 'History' }).click()
  await page.getByRole('button', { name: 'Create a new draft from this revision' }).click()
  expect(harness.requests.filter((item) => item.path.endsWith('/policies') && item.method === 'POST')).toHaveLength(1)
})

test('refuses the policy workspace when policies.read capability is missing', async ({ page }) => {
  const harness: Harness = { policies: [], requests: [], denied: true }; await install(page, harness)
  await page.goto(`/guild/${GUILD}/policies`)
  await expect(page.getByRole('alert')).toContainText('does not allow access to policies')
  await expect(page.getByRole('button', { name: 'Create draft' })).toHaveCount(0)
})
