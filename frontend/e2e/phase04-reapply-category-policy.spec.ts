import { expect, test, type Page } from '@playwright/test'

const USER = '700000000000000003'
const GUILD = '700000000000000001'
const ROLE = '700000000000000011'
const CAT = '700000000000000101'
const CHANNEL = '700000000000000201'
const CATEGORY_POLICY = '11111111-1111-4111-8111-111111111111'
const CHANNEL_POLICY = '22222222-2222-4222-8222-222222222222'
const PLAN_ID = '33333333-3333-4333-8333-333333333333'
const can = () => ({ outcome: 'CAN', causes: [], remediations: [] })

type Harness = { requests: Array<{ path: string; method: string; body: unknown }>; channelPolicyState: 'ACTIVE' | 'DISABLED' }

function policy(overrides: Record<string, unknown>) {
  return {
    guild_id: GUILD, policy_type: 'ACCESS_CONTROL', contract_version: 1, revision: 2, priority: 0, description: '',
    conditions: [{ kind: 'ALWAYS' }], effects: [{ kind: 'SET_ACCESS', access: 'VIEW', decision: 'ALLOW' }],
    metadata: { summary: 'x', tags: [], reason: null },
    created_by_user_id: USER, modified_by_user_id: USER, created_at: '2026-09-17T08:00:00Z', updated_at: '2026-09-17T08:00:00Z',
    activated_at: '2026-09-17T08:00:00Z', disabled_at: null, retired_at: null,
    ...overrides,
  }
}

function resolution(outcome: 'CAN' | 'CANNOT') {
  return { guild_id: GUILD, subject_id: '700000000000000301', decision: 'ACCESS_CONTROL:VIEW', outcome, target_scope_type: 'CHANNEL', target_scope_id: CHANNEL, target_state: 'CURRENT', target_freshness: 'FRESH', coverage: 'FULL', applicable_policies: [], contributions: [], conflicts: [], source_scopes: [], priority_trace: [], conditions: [], incomplete_reasons: [], warnings: [], source_versions: ['cache-v1'], discord_permissions: [], discord_allow_bits: '0', discord_deny_bits: '0', discord_translation_diagnostics: [] }
}

function disablePreview() {
  const entries = [{ target: { subject_id: '700000000000000301', scope_type: 'CHANNEL', scope_id: CHANNEL, requested_access: 'VIEW' }, current: resolution('CANNOT'), proposed: resolution('CAN'), access_change: 'GAINED', gained_contributions: ['cat'], lost_contributions: [], conflicts_created: [], conflicts_resolved: [], diagnostics: [], warnings: [], remediations: [] }]
  return { policy_id: CHANNEL_POLICY, policy_revision: 2, lifecycle_state: 'ACTIVE', scope_type: 'CHANNEL', scope_id: CHANNEL, entries, impact: { accuracy: 'EXACT', candidate_contexts: 1, evaluated_contexts: 1, affected_resources: 1, affected_roles: 1, affected_members: 1, access_gains: 1, access_losses: 0, conflicts: 0, impossible_or_incomplete_targets: 0, lower_bound_only: false, diagnostics: [] }, freshness: 'FRESH', coverage: 'FULL', source_versions: ['cache-v1'], warnings: [], persisted: false, discord_mutations: 0 }
}

async function install(page: Page, harness: Harness) {
  await page.route('**/health/features', (route) => route.fulfill({ json: { features: { oauth: true, live_events: true, portability: true } } }))
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request(); const path = new URL(request.url()).pathname; const method = request.method(); const body = request.postDataJSON() ?? null
    if (!['GET', 'HEAD'].includes(method)) harness.requests.push({ path, method, body })
    if (path === '/api/v1/ui/locales') return route.fulfill({ json: { catalog_version: 'v1', locales: [] } })
    if (path.startsWith('/api/v1/ui/locales/')) return route.fulfill({ status: 404, json: {} })
    if (path === '/api/v1/me') return route.fulfill({ json: { authenticated: true, user: { discord_user_id: USER, username: 'owner', global_name: 'Owner' }, active_guild_id: GUILD, csrf_token: 'csrf', policy_version: 1 } })
    if (path === '/api/v1/me/preferences') return route.fulfill({ json: { ui_locale_override_code: 'en', timezone: null } })
    if (path === '/api/v1/guilds') return route.fulfill({ json: { guilds: [{ guild_id: GUILD, name: 'Guild A', owner: true, permissions: '8', installation_status: 'ACTIVE' }] } })
    if (path.endsWith('/dashboard-capabilities')) return route.fulfill({ json: { guild_id: GUILD, source: 'AUTHORIZATION_AND_LOCAL_CACHE', discord_rest_calls: 0, user_capabilities: { 'tenant.read': can(), 'policies.read': can(), 'policies.create': can(), 'policies.update': can(), 'policies.activate': can(), 'plans.create': can() }, scoped_capabilities: { scope_kind: 'GUILD', scope_id: '*', capabilities: {} }, bot_operations: {}, coverage: 'FULL', completeness: 'FULL', freshness: 'FRESH' } })
    if (path.endsWith('/roles')) return route.fulfill({ json: { guild_id: GUILD, source: 'LOCAL_CACHE', discord_rest_calls: 0, roles: [{ id: ROLE, name: 'Managers', position: 5, permissions: '0', known_flags: [], unknown_bits: '0', managed: false, freshness: 'FRESH' }] } })
    if (path.endsWith('/structure')) { const base = { guild_id: GUILD, position: 0, resource_kind: 'CHANNEL', observability: 'VISIBLE', freshness: 'FRESH', data_assertion: 'CURRENT_CONFIRMED', threads: [] }; return route.fulfill({ json: { guild_id: GUILD, source: 'LOCAL_CACHE', discord_rest_calls: 0, categories: [{ ...base, id: CAT, type: 4, name: 'Direction', parent_id: null, channels: [{ ...base, id: CHANNEL, type: 0, name: 'board', parent_id: CAT }] }], root_channels: [] } }) }
    if (path.endsWith('/logical-groups')) return route.fulfill({ json: { guild_id: GUILD, groups: [] } })
    if (path.endsWith('/visibility-scopes')) return route.fulfill({ json: { guild_id: GUILD, scopes: [] } })
    if (path.endsWith('/policy-favorites')) return route.fulfill({ json: { guild_id: GUILD, favorite_keys: [] } })
    if (path.endsWith('/policies') && method === 'GET') {
      return route.fulfill({ json: { guild_id: GUILD, policies: [
        policy({ policy_id: CATEGORY_POLICY, name: 'Category master', scope_type: 'CATEGORY', scope_id: CAT, lifecycle_state: 'ACTIVE' }),
        policy({ policy_id: CHANNEL_POLICY, name: 'Board exception', scope_type: 'CHANNEL', scope_id: CHANNEL, lifecycle_state: harness.channelPolicyState }),
      ] } })
    }
    if (path.endsWith(`/policies/${CHANNEL_POLICY}/disable-preview`) && method === 'POST') return route.fulfill({ json: disablePreview() })
    if (path.endsWith(`/policies/${CHANNEL_POLICY}/disable-plan`) && method === 'POST') return route.fulfill({ status: 201, json: { created: true, preview: disablePreview(), plan: { id: PLAN_ID, status: 'VALIDATED', state_version: 2 }, preflight: { allowed: true, errors: [], warnings: [] } } })
    if (path.endsWith(`/policies/${CHANNEL_POLICY}/disable`) && method === 'POST') { harness.channelPolicyState = 'DISABLED'; return route.fulfill({ json: policy({ policy_id: CHANNEL_POLICY, name: 'Board exception', scope_type: 'CHANNEL', scope_id: CHANNEL, lifecycle_state: 'DISABLED', revision: 3 }) }) }
    if (path.endsWith('/plans')) return route.fulfill({ json: { guild_id: GUILD, plans: [] } })
    return route.fulfill({ status: 404, json: {} })
  })
}

test('reapplies the category policy on a channel-level exception: preview, plan, confirm, zero blind mutation', async ({ page }) => {
  const harness: Harness = { requests: [], channelPolicyState: 'ACTIVE' }
  await install(page, harness)
  await page.goto(`/guild/${GUILD}/policies`)
  await expect(page.getByRole('heading', { name: 'Access policies' })).toBeVisible()
  await page.getByLabel('Target resource').selectOption({ label: 'Text channel · Direction / board' })

  await page.getByText('Board exception').click()
  const reapplyButton = page.getByRole('button', { name: 'Reapply category policy' })
  await expect(reapplyButton).toBeVisible()
  await reapplyButton.click()

  await expect(page.getByText('Reapply the category policy', { exact: true })).toBeVisible()
  const reapplyImpactGrid = page.locator('.policy-preview-panel:has-text("Reapply the category policy") .policy-impact-grid')
  await expect(reapplyImpactGrid).toContainText('Access gains')

  await page.getByRole('button', { name: 'Prepare the plan' }).click()
  await expect(page.getByRole('button', { name: 'Confirm: reapply the category policy' })).toBeVisible()

  // Nothing mutated yet: still no /apply call and the channel policy is still ACTIVE server-side.
  expect(harness.requests.some((request) => request.path.includes('/apply'))).toBe(false)
  expect(harness.channelPolicyState).toBe('ACTIVE')

  await page.getByRole('button', { name: 'Confirm: reapply the category policy' }).click()
  await expect(page.getByText('The category policy has been reapplied.')).toBeVisible()

  const disableCall = harness.requests.find((request) => request.path.endsWith(`/policies/${CHANNEL_POLICY}/disable`))
  expect(disableCall).toBeDefined()
  expect((disableCall?.body as { plan_id: string }).plan_id).toBe(PLAN_ID)
  expect(harness.channelPolicyState).toBe('DISABLED')
  expect(harness.requests.some((request) => request.path.includes('/apply'))).toBe(false)
})
