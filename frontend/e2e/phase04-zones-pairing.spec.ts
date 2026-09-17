import { expect, test, type Page } from '@playwright/test'

const USER = '700000000000000003'
const GUILD = '700000000000000001'
const CAT_PUBLIC = '700000000000000101'
const CAT_STAFF = '700000000000000102'
const can = () => ({ outcome: 'CAN', causes: [], remediations: [] })

type Harness = { groups: Record<string, unknown>[]; requests: Array<{ path: string; method: string; body: unknown }> }

function structure() {
  const base = { guild_id: GUILD, position: 0, resource_kind: 'CATEGORY', observability: 'VISIBLE', freshness: 'FRESH', data_assertion: 'CURRENT_CONFIRMED', threads: [] }
  return {
    guild_id: GUILD, source: 'LOCAL_CACHE', discord_rest_calls: 0,
    categories: [
      { ...base, id: CAT_PUBLIC, type: 4, name: 'Direction publique', parent_id: null, channels: [] },
      { ...base, id: CAT_STAFF, type: 4, name: 'Direction staff', parent_id: null, channels: [] },
    ],
    root_channels: [],
  }
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
    if (path.endsWith('/roles')) return route.fulfill({ json: { guild_id: GUILD, source: 'LOCAL_CACHE', discord_rest_calls: 0, roles: [] } })
    if (path.endsWith('/structure')) return route.fulfill({ json: structure() })
    if (path.endsWith('/visibility-scopes')) return route.fulfill({ json: { guild_id: GUILD, scopes: [] } })
    if (path.endsWith('/policies') && method === 'GET') return route.fulfill({ json: { guild_id: GUILD, policies: [] } })
    if (path.endsWith('/logical-groups') && method === 'GET') return route.fulfill({ json: { guild_id: GUILD, resource_kind: 'DID_LOGICAL_RESOURCE', groups: harness.groups } })
    if (path.endsWith('/logical-groups') && method === 'POST') {
      const requestResources = (body as { resources: Array<{ resource_type: string; discord_resource_id: string; semantic_role: string }> }).resources
      const storedResources = requestResources.map((resource) => ({
        resource_type: resource.resource_type,
        discord_channel_id: resource.resource_type === 'ROLE' ? null : resource.discord_resource_id,
        discord_role_id: resource.resource_type === 'ROLE' ? resource.discord_resource_id : null,
        semantic_role: resource.semantic_role,
      }))
      const created = { id: 'g-new', guild_id: GUILD, name: (body as { name: string }).name, slug: (body as { slug: string }).slug, description: null, resources: storedResources }
      harness.groups.push(created)
      return route.fulfill({ status: 201, json: { guild_id: GUILD, id: 'g-new', resource_kind: 'DID_LOGICAL_RESOURCE' } })
    }
    if (path.endsWith('/plans')) return route.fulfill({ json: { guild_id: GUILD, plans: [] } })
    return route.fulfill({ status: 404, json: {} })
  })
}

test('links an existing public category with an existing staff category, zero fake Discord structure, persists across refetch', async ({ page }) => {
  const harness: Harness = { groups: [], requests: [] }
  await install(page, harness)
  await page.goto(`/guild/${GUILD}/policies`)
  await expect(page.getByRole('heading', { name: 'Access policies' })).toBeVisible()

  await page.getByText('Public zone + staff space').click()
  await page.getByRole('button', { name: 'Link a public + staff space' }).click()
  await page.getByLabel('Pairing name').fill('Direction publique + staff')
  await page.getByLabel('Public side').selectOption({ label: 'Category · Direction publique' })
  await page.getByLabel('Staff side').selectOption({ label: 'Category · Direction staff' })
  await page.getByRole('button', { name: 'Create the pairing' }).click()

  const zoneCard = page.locator('.zone-card', { hasText: 'Direction publique + staff' })
  await expect(zoneCard).toBeVisible()
  await expect(zoneCard).toContainText('DID grouping, not a Discord structure')
  const zoneSides = zoneCard.locator('.zone-side')
  await expect(zoneSides.nth(0)).toContainText('Public side')
  await expect(zoneSides.nth(0)).toContainText('Direction publique')
  await expect(zoneSides.nth(1)).toContainText('Staff side')
  await expect(zoneSides.nth(1)).toContainText('Direction staff')

  const createCall = harness.requests.find((request) => request.path.endsWith('/logical-groups') && request.method === 'POST')
  expect(createCall).toBeDefined()
  const createBody = createCall?.body as { resources: Array<{ resource_type: string; discord_resource_id: string; semantic_role: string }> }
  expect(createBody.resources).toEqual([
    { resource_type: 'CATEGORY', discord_resource_id: CAT_PUBLIC, semantic_role: 'did-zone-public' },
    { resource_type: 'CATEGORY', discord_resource_id: CAT_STAFF, semantic_role: 'did-zone-staff' },
  ])
  expect(harness.requests.some((request) => request.path.includes('apply'))).toBe(false)

  await page.reload()
  await expect(page.getByRole('heading', { name: 'Access policies' })).toBeVisible()
  await page.getByText('Public zone + staff space').click()
  await expect(page.getByText('Direction publique + staff', { exact: true })).toBeVisible()
})
