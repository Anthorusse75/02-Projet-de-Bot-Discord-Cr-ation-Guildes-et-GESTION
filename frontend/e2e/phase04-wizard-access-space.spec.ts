import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

const USER = '700000000000000003'
const GUILD = '700000000000000001'
const ROLE = '700000000000000011'
const CAT = '700000000000000101'
const CHANNEL = '700000000000000201'
const POLICY = '11111111-1111-4111-8111-111111111111'
const PLAN = '55555555-5555-4555-8555-555555555555'
const ROLE_PLAN = '77777777-7777-4777-8777-777777777777'

type Harness = { policies: Record<string, unknown>[]; requests: Array<{ path: string; method: string; body: unknown }> }
const can = () => ({ outcome: 'CAN', causes: [], remediations: [] })

function capabilities() {
  return {
    guild_id: GUILD, source: 'AUTHORIZATION_AND_LOCAL_CACHE', discord_rest_calls: 0,
    user_capabilities: { 'tenant.read': can(), 'policies.read': can(), 'policies.create': can(), 'policies.update': can(), 'policies.activate': can(), 'plans.create': can(), 'roles.write': can() },
    scoped_capabilities: { scope_kind: 'GUILD', scope_id: '*', capabilities: {} },
    bot_operations: { CREATE_ROLE: { ...can(), operation: 'CREATE_ROLE', required_permissions: ['MANAGE_ROLES'] } },
    coverage: 'FULL', completeness: 'FULL', freshness: 'FRESH',
  }
}

function roles() {
  return { guild_id: GUILD, source: 'LOCAL_CACHE', discord_rest_calls: 0, roles: [
    { id: ROLE, name: 'Managers', position: 5, permissions: '0', known_flags: [], unknown_bits: '0', managed: false, freshness: 'FRESH' },
  ] }
}

function structure() {
  const base = { guild_id: GUILD, position: 0, resource_kind: 'CHANNEL', observability: 'VISIBLE', freshness: 'FRESH', data_assertion: 'CURRENT_CONFIRMED', threads: [] }
  return { guild_id: GUILD, source: 'LOCAL_CACHE', discord_rest_calls: 0, categories: [{ ...base, id: CAT, type: 4, name: 'Direction', parent_id: null, channels: [{ ...base, id: CHANNEL, type: 0, name: 'board', parent_id: CAT }] }], root_channels: [] }
}

function policy(overrides: Record<string, unknown> = {}) {
  return {
    policy_id: POLICY, guild_id: GUILD, policy_type: 'ACCESS_CONTROL', contract_version: 1, name: 'Visible only to…', description: '', lifecycle_state: 'DRAFT', revision: 1,
    priority: 0, scope_type: 'CHANNEL', scope_id: CHANNEL, conditions: [{ kind: 'ALWAYS' }], effects: [{ kind: 'SET_ACCESS', access: 'VIEW', decision: 'ALLOW', audience: { mode: 'INCLUDE', match: 'ANY', role_ids: [ROLE] } }],
    metadata: { summary: '', tags: ['did-native:visible_only'], reason: null }, created_by_user_id: USER, modified_by_user_id: USER,
    created_at: '2026-09-15T08:00:00Z', updated_at: '2026-09-15T08:00:00Z', activated_at: null, disabled_at: null, retired_at: null, ...overrides,
  }
}

function preview() {
  const entry = { target: { subject_id: '700000000000000301', scope_type: 'CHANNEL', scope_id: CHANNEL, requested_access: 'VIEW' }, access_change: 'GAINED', gained_contributions: ['new'], lost_contributions: [], conflicts_created: [], conflicts_resolved: [], diagnostics: [], warnings: [], remediations: [],
    current: { guild_id: GUILD, subject_id: '700000000000000301', decision: 'x', outcome: 'CANNOT', target_scope_type: 'CHANNEL', target_scope_id: CHANNEL, target_state: 'CURRENT', target_freshness: 'FRESH', coverage: 'FULL', applicable_policies: [], contributions: [], conflicts: [], source_scopes: [], priority_trace: [], conditions: [], incomplete_reasons: [], warnings: [], source_versions: ['cache-v1'] },
    proposed: { guild_id: GUILD, subject_id: '700000000000000301', decision: 'x', outcome: 'CAN', target_scope_type: 'CHANNEL', target_scope_id: CHANNEL, target_state: 'CURRENT', target_freshness: 'FRESH', coverage: 'FULL', applicable_policies: [], contributions: [], conflicts: [], source_scopes: [], priority_trace: [], conditions: [], incomplete_reasons: [], warnings: [], source_versions: ['cache-v1'] } }
  return { policy_id: POLICY, policy_revision: 1, lifecycle_state: 'DRAFT', scope_type: 'CHANNEL', scope_id: CHANNEL, entries: [entry],
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
    if (path.endsWith('/policies') && method === 'GET') return route.fulfill({ json: { guild_id: GUILD, policies: harness.policies } })
    if (path.endsWith('/policies') && method === 'POST') { const created = policy(body as Record<string, unknown>); harness.policies.push(created); return route.fulfill({ status: 201, json: created }) }
    if (path.endsWith(`/policies/${POLICY}/preview`)) return route.fulfill({ json: preview() })
    if (path.endsWith(`/policies/${POLICY}/plan`)) return route.fulfill({ status: 201, json: { created: true, preview: preview(), plan: { id: PLAN, status: 'VALIDATED', state_version: 2 }, preflight: { allowed: true, errors: [], warnings: [] } } })
    if (path.endsWith('/plans') && method === 'POST') return route.fulfill({ status: 201, json: { plan: { id: ROLE_PLAN, state_version: 1, status: 'DRAFT' } } })
    if (path.endsWith(`/plans/${ROLE_PLAN}/validate`)) return route.fulfill({ json: { plan: { id: ROLE_PLAN, state_version: 2, status: 'VALIDATED', risk_level: 'LOW', impact: {}, reinforced_confirmation_required: false } } })
    if (path.endsWith('/plans') && method === 'GET') return route.fulfill({ json: { guild_id: GUILD, plans: [] } })
    return route.fulfill({ status: 404, json: {} })
  })
}

test('@a11y nominal: Assistants -> Configure access -> existing role -> Preview -> Policy DRAFT -> Plan, zero direct APPLY', async ({ page }) => {
  const harness: Harness = { policies: [], requests: [] }
  await install(page, harness)
  await page.goto(`/guild/${GUILD}/wizards`)
  await expect(page.getByRole('heading', { name: 'Assistants' })).toBeVisible()
  await page.getByRole('button', { name: 'Start' }).click()
  await expect(page).toHaveURL(new RegExp(`/guild/${GUILD}/wizards/access-space$`))

  await page.getByLabel('Target resource').selectOption(`TEXT_CHANNEL:${CHANNEL}`)
  await page.getByRole('button', { name: 'Next' }).click()

  await page.getByRole('button', { name: /Visible only to/ }).click()
  await page.getByRole('button', { name: 'Next' }).click()

  await page.getByRole('checkbox', { name: 'Managers' }).check()
  await page.getByRole('button', { name: 'Next' }).click()

  await page.getByRole('button', { name: 'Next' }).click() // conflicts step, informative only
  await page.getByRole('button', { name: 'Next' }).click() // adjust step, name pre-filled

  await page.getByRole('button', { name: 'Create the draft and preview' }).click()
  await expect(page.getByText('A Policy DRAFT was created. Discord was not changed.')).toBeVisible()
  await expect(page.getByText('Exact impact')).toBeVisible()
  const accessibility = await new AxeBuilder({ page }).include('#main').analyze()
  expect(accessibility.violations.filter((item) => ['serious', 'critical'].includes(item.impact ?? ''))).toEqual([])

  await page.getByRole('button', { name: 'Next' }).click() // plan step
  await page.getByRole('button', { name: 'Prepare plan' }).click()
  await expect(page).toHaveURL(new RegExp(`/guild/${GUILD}/plans$`))

  expect(harness.requests.some((item) => item.path.endsWith('/policies') && item.method === 'POST')).toBe(true)
  expect(harness.requests.some((item) => item.path.endsWith(`/policies/${POLICY}/plan`))).toBe(true)
  expect(harness.requests.some((item) => /apply/i.test(item.path))).toBe(false)
  const createdPolicyBody = harness.requests.find((item) => item.path.endsWith('/policies') && item.method === 'POST')?.body as { effects: Array<{ audience?: { role_ids: string[] } }> }
  expect(createdPolicyBody.effects[0]?.audience?.role_ids).toEqual([ROLE])
})

test('missing role: proposal blocks progress (CANNOT) until resolved, role plan stays validated-only, and the proposed role never reaches the Policy', async ({ page }) => {
  const harness: Harness = { policies: [], requests: [] }
  await install(page, harness)
  await page.goto(`/guild/${GUILD}/wizards/access-space`)

  await page.getByLabel('Target resource').selectOption(`TEXT_CHANNEL:${CHANNEL}`)
  await page.getByRole('button', { name: 'Next' }).click()
  await page.getByRole('button', { name: /Visible only to/ }).click()
  await page.getByRole('button', { name: 'Next' }).click()

  await page.getByRole('button', { name: '+ Create a role' }).click()
  await page.getByLabel('Role name').fill('Confirmed members')
  await page.getByRole('button', { name: 'Add this proposal' }).click()
  await expect(page.getByText('Will be created')).toBeVisible()
  await expect(page.getByText(/proposed role does not exist yet/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Next' })).toBeDisabled()

  await page.getByRole('checkbox', { name: 'Managers' }).check()
  await expect(page.getByRole('button', { name: 'Next' })).toBeEnabled()
  await page.getByRole('button', { name: 'Next' }).click()

  await page.getByRole('button', { name: 'Next' }).click() // conflicts
  await page.getByRole('button', { name: 'Next' }).click() // adjust
  await page.getByRole('button', { name: 'Create the draft and preview' }).click()
  await expect(page.getByText('Exact impact')).toBeVisible()
  await page.getByRole('button', { name: 'Next' }).click() // plan

  await page.getByRole('button', { name: 'Prepare the role plan' }).click()
  await expect(page.getByText('Role plan validated. No Discord role exists yet.')).toBeVisible()
  await page.getByRole('button', { name: 'Prepare plan' }).click()
  await expect(page).toHaveURL(new RegExp(`/guild/${GUILD}/plans$`))

  expect(harness.requests.some((item) => /apply/i.test(item.path))).toBe(false)
  const rolePlanRequest = harness.requests.find((item) => item.path.endsWith('/plans') && item.method === 'POST')?.body as { nodes: Array<{ discord_id?: string; symbol?: string; properties?: { name?: string } }> }
  expect(rolePlanRequest.nodes[0]?.discord_id).toBeUndefined()
  expect(rolePlanRequest.nodes[0]?.symbol).toBeTruthy()
  expect(rolePlanRequest.nodes[0]?.properties?.name).toBe('Confirmed members')
  const createdPolicyBody = harness.requests.find((item) => item.path.endsWith('/policies') && item.method === 'POST')?.body as { effects: Array<{ audience?: { role_ids: string[] } }> }
  expect(createdPolicyBody.effects[0]?.audience?.role_ids).toEqual([ROLE])
})
