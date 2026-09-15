import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

const USER = '700000000000000003'
const GUILD = '700000000000000001'
const ROLE = '700000000000000011'
const GUEST = '700000000000000012'
const CAT = '700000000000000101'
const CHANNEL = '700000000000000201'
const VOICE = '700000000000000202'
const ROOT_CHANNEL = '700000000000000203'
const POLICY_IDS = ['11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222']

type RequestLog = { path: string; method: string; body: unknown }
const can = () => ({ outcome: 'CAN', causes: [], remediations: [] })

function resolution(scopeId: string, outcome: 'CAN' | 'CANNOT') {
  return { guild_id: GUILD, subject_id: USER, decision: 'ACCESS_CONTROL:VIEW', outcome, target_scope_type: scopeId === CAT ? 'CATEGORY' : 'CHANNEL', target_scope_id: scopeId, target_state: 'CURRENT', target_freshness: 'FRESH', coverage: 'FULL', applicable_policies: [], contributions: [], conflicts: [], source_scopes: [], priority_trace: [], conditions: [], incomplete_reasons: [], warnings: [], source_versions: ['cache-v1'] }
}

function preview(policyId: string, scopeId: string) {
  return { policy_id: policyId, policy_revision: 1, lifecycle_state: 'DRAFT', scope_type: scopeId === CAT ? 'CATEGORY' : 'CHANNEL', scope_id: scopeId, entries: [{ target: { subject_id: USER, scope_type: scopeId === CAT ? 'CATEGORY' : 'CHANNEL', scope_id: scopeId, requested_access: 'VIEW' }, current: resolution(scopeId, 'CANNOT'), proposed: resolution(scopeId, 'CAN'), access_change: 'GAINED', gained_contributions: ['new'], lost_contributions: [], conflicts_created: [], conflicts_resolved: [], diagnostics: [], warnings: [], remediations: [] }], impact: { accuracy: 'EXACT', candidate_contexts: 1, evaluated_contexts: 1, affected_resources: 1, affected_roles: 1, affected_members: 1, access_gains: 1, access_losses: 0, conflicts: 0, impossible_or_incomplete_targets: 0, lower_bound_only: false, diagnostics: [] }, freshness: 'FRESH', coverage: 'FULL', source_versions: ['cache-v1'], warnings: [], persisted: false, discord_mutations: 0 }
}

async function install(page: Page, requests: RequestLog[]) {
  let matrixReads = 0
  await page.route('**/health/features', (route) => route.fulfill({ json: { features: { oauth: true, live_events: true, portability: true } } }))
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request(); const path = new URL(request.url()).pathname; const method = request.method(); const body = request.postDataJSON() ?? null
    if (!['GET', 'HEAD'].includes(method)) requests.push({ path, method, body })
    if (path === '/api/v1/ui/locales') return route.fulfill({ json: { locales: [] } })
    if (path.startsWith('/api/v1/ui/locales/')) return route.fulfill({ status: 404, json: {} })
    if (path === '/api/v1/me') return route.fulfill({ json: { authenticated: true, user: { discord_user_id: USER, username: 'owner', global_name: 'Owner' }, active_guild_id: GUILD, csrf_token: 'csrf', policy_version: 1 } })
    if (path === '/api/v1/guilds') return route.fulfill({ json: { guilds: [{ guild_id: GUILD, name: 'Guild A', owner: true, permissions: '8', installation_status: 'ACTIVE' }] } })
    if (path.endsWith('/dashboard-capabilities')) return route.fulfill({ json: { guild_id: GUILD, source: 'AUTHORIZATION_AND_LOCAL_CACHE', discord_rest_calls: 0, user_capabilities: { 'policies.read': can(), 'permissions.read': can(), 'policies.create': can(), 'policies.activate': can(), 'plans.create': can() }, scoped_capabilities: { scope_kind: 'GUILD', scope_id: '*', capabilities: {} }, bot_operations: {}, coverage: 'FULL', completeness: 'FULL', freshness: 'FRESH' } })
    if (path.endsWith('/roles')) return route.fulfill({ json: { guild_id: GUILD, source: 'LOCAL_CACHE', discord_rest_calls: 0, roles: [{ id: ROLE, name: 'Managers', position: 5, permissions: '0', known_flags: [], unknown_bits: '0', managed: false, freshness: 'FRESH' }, { id: GUEST, name: 'Guests', position: 4, permissions: '0', known_flags: [], unknown_bits: '0', managed: false, freshness: 'FRESH' }] } })
    if (path.endsWith('/structure')) { const base = { guild_id: GUILD, position: 0, resource_kind: 'CHANNEL', observability: 'VISIBLE', freshness: 'FRESH', data_assertion: 'CURRENT_CONFIRMED', threads: [] }; return route.fulfill({ json: { guild_id: GUILD, source: 'LOCAL_CACHE', discord_rest_calls: 0, categories: [{ ...base, id: CAT, type: 4, name: 'Direction', parent_id: null, channels: [{ ...base, id: CHANNEL, type: 0, name: 'board', parent_id: CAT }] }], root_channels: [{ ...base, id: ROOT_CHANNEL, type: 0, name: 'news', parent_id: null }, { ...base, id: VOICE, type: 2, name: 'Lounge', parent_id: null }] } }) }
    if (path.endsWith('/policies') && method === 'GET') return route.fulfill({ json: { guild_id: GUILD, policies: [] } })
    if (path.endsWith('/access-matrix/resolve')) { matrixReads += 1; const cells = [ROLE, GUEST].flatMap((roleId) => [CAT, CHANNEL, ROOT_CHANNEL, VOICE].map((resourceId) => ({ role_id: roleId, resource_id: resourceId, synthesis: resourceId === CHANNEL && roleId === ROLE ? 'WRITE' : resourceId === VOICE ? 'SPEAK' : 'NONE', permission_status: 'COMPLETE', policy_outcome: 'CAN', conflict: resourceId === CHANNEL && roleId === ROLE, exception: resourceId === CAT && roleId === ROLE, inherited: resourceId === CAT && roleId === ROLE, contributing_policy_ids: [], conflict_policy_ids: [], incomplete_reasons: [], role_known: true, resource_known: true }))); return route.fulfill({ json: { guild_id: GUILD, coverage: 'FULL', freshness: 'FRESH', source_versions: [`cache-${matrixReads}`], cells } }) }
    if (path.endsWith('/policies/bulk-preview')) { const definitions = (body as {definitions: Array<Record<string, unknown>>}).definitions; const items = definitions.map((definition, index) => { const policyId = POLICY_IDS[index] ?? `33333333-3333-4333-8333-${String(index).padStart(12, '0')}`; const scopeId = String(definition.scope_id); return { policy: { ...definition, policy_id: policyId, guild_id: GUILD, lifecycle_state: 'DRAFT', revision: 1, created_by_user_id: USER, modified_by_user_id: USER, created_at: null, updated_at: null, activated_at: null, disabled_at: null, retired_at: null }, preview: preview(policyId, scopeId) } }); return route.fulfill({ status: 201, json: { operation_id: 'operation', draft_count: items.length, discord_mutations: 0, items } }) }
    if (path.endsWith('/policies/bulk-plan')) { const policies = (body as {policies: Array<{policy_id:string}>}).policies; return route.fulfill({ status: 201, json: { prepared_count: policies.length, discord_mutations: 0, items: policies.map(({ policy_id }) => ({ policy_id, created: true, plan: { id: policy_id, guild_id: GUILD, status: 'VALIDATED', state_version: 2, plan_hash: 'hash', risk_level: 'LOW', impact: {}, reinforced_confirmation_required: false, created_at: '', updated_at: '', error_code: null }, preflight: { allowed: true, errors: [], warnings: [] } })) } }) }
    return route.fulfill({ status: 404, json: {} })
  })
  return () => matrixReads
}

test('@a11y matrix cell exposes synthesis, conflict, Discord details and an intention-first Preview', async ({ page }) => {
  const requests: RequestLog[] = []; const matrixReads = await install(page, requests)
  await page.goto(`/guild/${GUILD}/matrix`)
  await page.getByRole('button', { name: /Managers and board: Write/ }).click()
  await expect(page.getByText('Conflict', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Change the intended access' })).toBeVisible()
  await page.getByRole('button', { name: 'Discord details' }).click()
  await expect(page.getByText(/permission_status/)).toBeVisible()
  await page.getByRole('button', { name: 'Create DRAFT and preview' }).click()
  await expect(page.getByText(/Before:.*Denied/)).toBeVisible()
  await expect(page.getByText(/After:.*Allowed/)).toBeVisible()
  await page.getByRole('button', { name: 'Refresh data' }).click()
  expect(matrixReads()).toBeGreaterThan(1)
  const accessibility = await new AxeBuilder({ page }).include('#main').analyze()
  expect(accessibility.violations.filter((item) => ['serious', 'critical'].includes(item.impact ?? ''))).toEqual([])
  await page.getByRole('button', { name: 'Prepare plan(s)' }).click()
  await expect(page.getByText('1 plan(s) prepared')).toBeVisible()
  expect(requests.some((item) => /apply/i.test(item.path))).toBe(false)
})

test('bulk selection excludes incompatible resources, previews every compatible target and reports the real Plan count', async ({ page }) => {
  const requests: RequestLog[] = []; await install(page, requests)
  await page.goto(`/guild/${GUILD}/matrix`)
  await page.getByRole('checkbox', { name: /board/ }).check()
  await page.getByRole('checkbox', { name: /news/ }).check()
  await page.getByRole('checkbox', { name: /Lounge/ }).check()
  await expect(page.getByText('3 selected', { exact: true }).last()).toBeVisible()
  await expect(page.getByText('2 compatible', { exact: true })).toBeVisible()
  await expect(page.getByText('1 excluded', { exact: true })).toBeVisible()
  await expect(page.getByText('This Policy does not support voice channels.')).toBeVisible()
  await page.getByRole('group', { name: 'Roles / audience' }).getByText('Managers').click()
  await page.getByRole('button', { name: 'Create DRAFTs and preview' }).click()
  await expect(page.getByText('2 DRAFT(s)')).toBeVisible()
  await page.getByRole('button', { name: 'Prepare plan(s)' }).click()
  await expect(page.getByText('2 plan(s) prepared')).toBeVisible()
  const previewRequest = requests.find((item) => item.path.endsWith('/policies/bulk-preview'))
  expect((previewRequest?.body as {definitions: unknown[]}).definitions).toHaveLength(2)
  expect(requests.filter((item) => item.path.endsWith('/policies/bulk-plan'))).toHaveLength(1)
  expect(requests.some((item) => /apply/i.test(item.path))).toBe(false)
})
