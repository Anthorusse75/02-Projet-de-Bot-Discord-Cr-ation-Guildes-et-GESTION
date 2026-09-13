import { expect, test, type Page } from '@playwright/test'

const USER = '700000000000000003'
const GUILD_A = '700000000000000001'
const GUILD_B = '700000000000000002'
const CAT_GENERAL = '700000000000000101'
const CAT_PROJECTS = '700000000000000102'
const CHANNEL_WELCOME = '700000000000000201'
const CHANNEL_ROADMAP = '700000000000000202'
const THREAD_RELEASE = '700000000000000301'
const B_CAT = '700000000000000401'

type CapturedPlan = { schema_version?: string; nodes?: Array<{ discord_id?: string; resource_type?: string; properties?: Record<string, unknown> }> }

function channel(id: string, name: string, position: number, parentId: string | null, type = 0, threads: unknown[] = []) {
  return { guild_id: GUILD_A, id, type, name, position, parent_id: parentId, resource_kind: type === 4 ? 'CATEGORY' : 'CHANNEL', observability: 'OBSERVED', freshness: 'FRESH', data_assertion: 'KNOWN', threads }
}

function structureA() {
  const thread = channel(THREAD_RELEASE, 'release-notes', 0, CHANNEL_ROADMAP, 11)
  return {
    guild_id: GUILD_A,
    source: 'LOCAL_CACHE',
    discord_rest_calls: 0,
    categories: [
      { ...channel(CAT_GENERAL, 'General', 0, null, 4), channels: [channel(CHANNEL_WELCOME, 'welcome', 0, CAT_GENERAL)] },
      { ...channel(CAT_PROJECTS, 'Projects', 1, null, 4), channels: [channel(CHANNEL_ROADMAP, 'roadmap', 0, CAT_PROJECTS, 0, [thread])] },
    ],
    root_channels: [channel('700000000000000203', 'lobby', 2, null)],
  }
}

function structureB() {
  return {
    guild_id: GUILD_B,
    source: 'LOCAL_CACHE',
    discord_rest_calls: 0,
    categories: [{
      guild_id: GUILD_B, id: B_CAT, type: 4, name: 'Destination', position: 0, parent_id: null,
      resource_kind: 'CATEGORY', observability: 'OBSERVED', freshness: 'FRESH', data_assertion: 'KNOWN', channels: [],
    }],
    root_channels: [],
  }
}

function capabilities(guildId: string) {
  const can = { outcome: 'CAN', causes: [], remediations: [] }
  return {
    guild_id: guildId,
    source: 'AUTHORIZATION_AND_LOCAL_CACHE',
    discord_rest_calls: 0,
    user_capabilities: { 'structure.read': can, 'structure.write': can, 'plans.create': can, 'permissions.read': can },
    scoped_capabilities: { scope_kind: 'GUILD', scope_id: '*', capabilities: { 'structure.write': can } },
    bot_operations: {
      REORDER_CHANNELS: { ...can, operation: 'REORDER_CHANNELS', required_permissions: [] },
      CREATE_CHANNEL: { ...can, operation: 'CREATE_CHANNEL', required_permissions: [] },
    },
    coverage: 'FULL', completeness: 'FULL', freshness: 'FRESH',
  }
}

async function installRoutes(page: Page, captured: { plans: CapturedPlan[] }) {
  await page.route('**/health/features', (route) => route.fulfill({ json: { features: { oauth: true, live_events: true, portability: true } } }))
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    const method = request.method()

    if (path === '/api/v1/ui/locales') return route.fulfill({ json: { catalog_version: 'did-ui-v2', locales: [] } })
    if (path.startsWith('/api/v1/ui/locales/')) return route.fulfill({ status: 404, json: {} })
    if (path === '/api/v1/me') return route.fulfill({ json: { authenticated: true, user: { discord_user_id: USER, username: 'owner', global_name: 'Owner' }, active_guild_id: GUILD_A, csrf_token: 'csrf', policy_version: 1 } })
    if (path === '/api/v1/me/preferences') return route.fulfill({ json: { ui_locale_override_code: 'en', timezone: null } })
    if (path === '/api/v1/guilds' && method === 'GET') return route.fulfill({ json: { guilds: [
      { guild_id: GUILD_A, name: 'Guild A', owner: true, permissions: '8', installation_status: 'ACTIVE' },
      { guild_id: GUILD_B, name: 'Guild B', owner: true, permissions: '8', installation_status: 'ACTIVE' },
    ] } })
    if (path === `/api/v1/guilds/${GUILD_A}/structure`) return route.fulfill({ json: structureA() })
    if (path === `/api/v1/guilds/${GUILD_B}/structure`) return route.fulfill({ json: structureB() })
    if (path === `/api/v1/guilds/${GUILD_A}/dashboard-capabilities`) return route.fulfill({ json: capabilities(GUILD_A) })
    if (path === `/api/v1/guilds/${GUILD_B}/dashboard-capabilities`) return route.fulfill({ json: capabilities(GUILD_B) })
    if (path === `/api/v1/guilds/${GUILD_A}/plans` && method === 'POST') {
      captured.plans.push(request.postDataJSON() as CapturedPlan)
      return route.fulfill({ json: { plan: { id: '11111111-1111-4111-8111-111111111111', state_version: 1 } } })
    }
    if (path === `/api/v1/guilds/${GUILD_A}/plans/11111111-1111-4111-8111-111111111111/validate` && method === 'POST') return route.fulfill({ json: { status: 'VALIDATED' } })
    if (path === `/api/v1/guilds/${GUILD_A}/plans` && method === 'GET') return route.fulfill({ json: { plans: [] } })
    return route.fulfill({ status: 404, json: {} })
  })
}

function resourceRow(page: Page, name: string) {
  // Target the exact resource node. An ancestor category also contains all nested
  // channel text, so text-only treeitem matching can silently drag the parent.
  return page.locator(`[role="treeitem"][data-drop-name="${name}"] > .structure-resource-row`).first()
}

async function expandResource(page: Page, name: string) {
  const row = resourceRow(page, name)
  const expander = row.locator('.resource-expander:not(.placeholder)')
  await expect(expander).toBeVisible()
  await expander.click()
}

async function drag(page: Page, sourceText: string, targetText: string, button: 'left'|'right' = 'left') {
  const source = resourceRow(page, sourceText)
  const target = resourceRow(page, targetText)
  const sourceBox = await source.boundingBox()
  const targetBox = await target.boundingBox()
  if (!sourceBox || !targetBox) throw new Error('drag target is not visible')
  await page.mouse.move(sourceBox.x + Math.min(85, sourceBox.width * .55), sourceBox.y + sourceBox.height / 2)
  await page.mouse.down({ button })
  await page.mouse.move(sourceBox.x + Math.min(105, sourceBox.width * .7), sourceBox.y + sourceBox.height / 2, { steps: 3 })
  await page.mouse.move(targetBox.x + Math.min(90, targetBox.width * .55), targetBox.y + targetBox.height / 2, { steps: 8 })
  await page.mouse.up({ button })
}

test('explorer renders faithful hierarchy, selection inspector, compact language control and survives reload', async ({ page }) => {
  const captured = { plans: [] as CapturedPlan[] }
  await installRoutes(page, captured)
  await page.goto(`/guild/${GUILD_A}/structure`)

  await expect(page.getByRole('heading', { name: 'Discord structure' })).toBeVisible()
  await expect(page.getByText('2 categories')).toBeVisible()
  await expect(page.getByText('3 channels')).toBeVisible()
  await expect(page.getByText('1 threads')).toBeVisible()
  await expect(resourceRow(page, 'General')).toBeVisible()
  await expect(resourceRow(page, 'welcome')).toBeVisible()
  await expect(resourceRow(page, 'roadmap')).toBeVisible()
  await expandResource(page, 'roadmap')
  await expect(resourceRow(page, 'release-notes')).toBeVisible()

  await resourceRow(page, 'welcome').click()
  await expect(page.getByText(CHANNEL_WELCOME, { exact: true }).last()).toBeVisible()
  await expect(page.getByText('Channel', { exact: true }).last()).toBeVisible()

  const locale = page.locator('.locale-control')
  await expect(locale.locator('.locale-code')).toHaveText('EN')
  await expect(locale.locator('.locale-flag')).toHaveCount(0)

  await page.reload()
  await expect(resourceRow(page, 'General')).toBeVisible()
  await expect(resourceRow(page, 'welcome')).toBeVisible()
  await expect(resourceRow(page, 'roadmap')).toBeVisible()
  await expandResource(page, 'roadmap')
  await expect(resourceRow(page, 'release-notes')).toBeVisible()
})

test('left drag channel into category creates a proposal with Discord parent_id and no direct mutation', async ({ page }) => {
  const captured = { plans: [] as CapturedPlan[] }
  await installRoutes(page, captured)
  await page.goto(`/guild/${GUILD_A}/structure`)

  await drag(page, 'welcome', 'Projects')
  await expect(page.getByRole('dialog', { name: 'Review proposed action' })).toBeVisible()
  await expect(page.getByText('No Discord mutation occurs until a plan is confirmed and applied.')).toBeVisible()
  await page.getByRole('button', { name: 'Preview' }).click()
  await expect(page).toHaveURL(new RegExp(`/guild/${GUILD_A}/plans$`))

  expect(captured.plans).toHaveLength(1)
  expect(captured.plans[0]?.nodes?.[0]).toMatchObject({
    discord_id: CHANNEL_WELCOME,
    resource_type: 'CHANNEL',
    properties: { parent_id: CAT_PROJECTS },
  })
})

test('category-to-category drag compiles a position reorder without fake category nesting', async ({ page }) => {
  const captured = { plans: [] as CapturedPlan[] }
  await installRoutes(page, captured)
  await page.goto(`/guild/${GUILD_A}/structure`)

  await drag(page, 'Projects', 'General')
  await expect(page.getByRole('dialog', { name: 'Review proposed action' })).toBeVisible()
  await page.getByRole('button', { name: 'Preview' }).click()

  const node = captured.plans[0]?.nodes?.[0]
  expect(node).toMatchObject({ discord_id: CAT_PROJECTS, resource_type: 'CATEGORY', properties: { position: 0 } })
  expect(node?.properties).not.toHaveProperty('parent_id')
})

test('right drag to another server exposes only safe cross-server actions', async ({ page }) => {
  const captured = { plans: [] as CapturedPlan[] }
  await installRoutes(page, captured)
  const destinationCapabilitiesReady = page.waitForResponse((response) => new URL(response.url()).pathname === `/api/v1/guilds/${GUILD_B}/dashboard-capabilities` && response.ok())
  await page.goto(`/guild/${GUILD_A}/structure`)
  await destinationCapabilitiesReady
  await page.waitForTimeout(150)

  const source = resourceRow(page, 'welcome')
  const target = page.locator('.destination-guild-row').filter({ hasText: 'Guild B' }).first()
  const sourceBox = await source.boundingBox()
  const targetBox = await target.boundingBox()
  if (!sourceBox || !targetBox) throw new Error('cross-server drag target is not visible')
  await page.mouse.move(sourceBox.x + Math.min(85, sourceBox.width * .55), sourceBox.y + sourceBox.height / 2)
  await page.mouse.down({ button: 'right' })
  await page.mouse.move(sourceBox.x + Math.min(105, sourceBox.width * .7), sourceBox.y + sourceBox.height / 2, { steps: 3 })
  await page.mouse.move(targetBox.x + Math.min(70, targetBox.width * .45), targetBox.y + targetBox.height / 2, { steps: 8 })
  await expect(target).toHaveClass(/drop-hover/)
  await page.mouse.up({ button: 'right' })

  const menu = page.getByRole('menu', { name: 'Choose a drop action' })
  await expect(menu).toBeVisible()
  await expect(menu.getByRole('menuitem', { name: 'Copy as new' })).toBeEnabled()
  await expect(menu.getByRole('menuitem', { name: 'Clone with dependencies' })).toBeEnabled()
  await expect(menu.getByRole('menuitem', { name: 'Propose move' })).toHaveCount(0)
  expect(captured.plans).toHaveLength(0)
})
