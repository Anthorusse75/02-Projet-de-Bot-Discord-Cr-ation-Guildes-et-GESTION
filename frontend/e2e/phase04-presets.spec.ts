import { expect, test, type Page } from '@playwright/test'

const USER = '700000000000000003'
const GUILD = '700000000000000001'
const CAT = '700000000000000101'
const CHANNEL = '700000000000000201'
const ROLE_ADMIN = '700000000000000011'
const ROLE_VIP = '700000000000000012'
const can = () => ({ outcome: 'CAN', causes: [], remediations: [] })

type Harness = { policies: Record<string, unknown>[]; requests: Array<{ path: string; method: string; body: unknown }> }

function structure() {
  const base = { guild_id: GUILD, position: 0, resource_kind: 'CATEGORY', observability: 'VISIBLE', freshness: 'FRESH', data_assertion: 'CURRENT_CONFIRMED', threads: [] }
  return { guild_id: GUILD, source: 'LOCAL_CACHE', discord_rest_calls: 0, categories: [{ ...base, id: CAT, type: 4, name: 'Direction', parent_id: null, channels: [{ ...base, id: CHANNEL, type: 0, name: 'announcements', parent_id: CAT, resource_kind: 'CHANNEL' }] }], root_channels: [] }
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
    if (path.endsWith('/roles')) return route.fulfill({ json: { guild_id: GUILD, source: 'LOCAL_CACHE', discord_rest_calls: 0, roles: [{ id: ROLE_ADMIN, name: 'Admins', position: 5, permissions: '0', known_flags: [], unknown_bits: '0', managed: false, freshness: 'FRESH' }, { id: ROLE_VIP, name: 'VIP', position: 4, permissions: '0', known_flags: [], unknown_bits: '0', managed: false, freshness: 'FRESH' }] } })
    if (path.endsWith('/structure')) return route.fulfill({ json: structure() })
    if (path.endsWith('/logical-groups')) return route.fulfill({ json: { guild_id: GUILD, groups: [] } })
    if (path.endsWith('/visibility-scopes')) return route.fulfill({ json: { guild_id: GUILD, scopes: [] } })
    if (path.endsWith('/policy-favorites')) return route.fulfill({ json: { guild_id: GUILD, favorite_keys: [] } })
    if (path.endsWith('/policies') && method === 'GET') return route.fulfill({ json: { guild_id: GUILD, policies: harness.policies } })
    if (path.endsWith('/policies') && method === 'POST') {
      const created = { policy_id: crypto.randomUUID(), guild_id: GUILD, policy_type: 'ACCESS_CONTROL', contract_version: 1, lifecycle_state: 'DRAFT', revision: 1, created_by_user_id: USER, modified_by_user_id: USER, created_at: null, updated_at: null, activated_at: null, disabled_at: null, retired_at: null, ...(body as Record<string, unknown>) }
      harness.policies.push(created)
      return route.fulfill({ status: 201, json: created })
    }
    if (path.endsWith('/plans')) return route.fulfill({ json: { guild_id: GUILD, plans: [] } })
    return route.fulfill({ status: 404, json: {} })
  })
}

test('confidential preset shows every sub-rule before creating anything, then creates one draft per sub-rule with zero APPLY', async ({ page }) => {
  const harness: Harness = { policies: [], requests: [] }
  await install(page, harness)
  await page.goto(`/guild/${GUILD}/policies`)
  await expect(page.getByRole('heading', { name: 'Access policies' })).toBeVisible()
  await page.getByLabel('Target resource').selectOption({ label: 'Category · Direction' })

  await page.getByText('Presets', { exact: true }).click()
  await page.getByRole('button', { name: /Confidential/ }).click()

  // No sub-rule should be listed until roles are actually chosen.
  await expect(page.getByText('Sub-rules this preset will activate')).toBeVisible()
  await expect(page.getByText('@everyone and @here mentions are blocked')).toBeVisible()
  await expect(page.getByText(/Visible only to:/)).not.toBeVisible()

  await page.getByRole('group', { name: 'Who can see this resource?' }).getByText('VIP').click()
  await page.getByRole('group', { name: 'Who can manage this resource?' }).getByText('Admins').click()

  await expect(page.getByText('Visible only to: VIP')).toBeVisible()
  await expect(page.getByText('Managed only by: Admins')).toBeVisible()
  await expect(page.getByText('Thread creation is limited to: Admins')).toBeVisible()

  const createButton = page.getByRole('button', { name: 'Create the preset policies' })
  await createButton.click()

  await expect(page.getByText('4 policy draft(s) created from this preset.')).toBeVisible()

  const createCalls = harness.requests.filter((request) => request.path.endsWith('/policies') && request.method === 'POST')
  expect(createCalls).toHaveLength(4)
  const groupTags = new Set(createCalls.map((request) => (request.body as { metadata: { tags: string[] } }).metadata.tags.find((tag) => tag.startsWith('preset-group:'))))
  expect(groupTags.size).toBe(1)
  expect(harness.requests.some((request) => request.path.includes('apply'))).toBe(false)

  await expect(page.getByText('Confidential (Visibility)')).toBeVisible()
  await expect(page.getByText('Confidential (Management)')).toBeVisible()
  await expect(page.getByText('Confidential (Mentions)')).toBeVisible()
  await expect(page.getByText('Confidential (Threads)')).toBeVisible()
})

test('@a11y announcement preset separates reactions, thread creation and replies in threads', async ({ page }) => {
  const harness: Harness = { policies: [], requests: [] }
  await install(page, harness)
  await page.goto(`/guild/${GUILD}/policies`)
  await page.getByLabel('Target resource').selectOption(`TEXT_CHANNEL:${CHANNEL}`)
  await page.getByText('Presets', { exact: true }).click()
  await page.getByRole('button', { name: /^Announcement channel/ }).click()
  await page.getByRole('group', { name: 'Who can publish here?' }).getByText('VIP').click()
  await page.getByRole('combobox', { name: /^Reactions/ }).selectOption('EVERYONE')
  await page.getByRole('combobox', { name: /^Thread creation/ }).selectOption('NONE')
  await page.getByRole('combobox', { name: /^Replies in threads/ }).selectOption('ONLY')

  await expect(page.getByText('Everyone can react')).toBeVisible()
  await expect(page.getByText('No one can start a thread')).toBeVisible()
  await expect(page.getByText('Only these publishers can reply in threads: VIP')).toBeVisible()
  await expect(page.getByText(/Replies in the main channel still follow the publishing permission/)).toBeVisible()
  await page.getByRole('button', { name: 'Create the preset policies' }).click()
  await expect(page.getByText('4 policy draft(s) created from this preset.')).toBeVisible()

  const createCalls = harness.requests.filter((request) => request.path.endsWith('/policies') && request.method === 'POST')
  expect(createCalls).toHaveLength(4)
  const accesses = createCalls.map((request) => (request.body as {effects:Array<{access:string}>}).effects[0]?.access)
  expect(accesses).toEqual(['WRITE', 'REACT', 'CREATE_THREAD', 'PARTICIPATE_THREAD'])
  expect(harness.requests.some((request) => request.path.includes('apply'))).toBe(false)
})
