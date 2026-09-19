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
type LogicalGroupPatch = { name: string; description: string | null; metadata: Record<string, unknown>; slug?: string; resources?: unknown[] }
type Captured = { plans: CapturedPlan[]; logicalGroupPatches?: LogicalGroupPatch[] }
type RouteOptions = {
  denyMove?: boolean
  structureAProvider?: () => ReturnType<typeof structureA>
}

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

function capabilities(guildId: string, denyMove = false) {
  const can = { outcome: 'CAN', causes: [], remediations: [] }
  const cannot = { outcome: 'CANNOT', causes: ['MISSING_CAPABILITY'], remediations: ['Grant the required capability.'] }
  return {
    guild_id: guildId,
    source: 'AUTHORIZATION_AND_LOCAL_CACHE',
    discord_rest_calls: 0,
    user_capabilities: { 'structure.read': can, 'structure.write': denyMove ? cannot : can, 'plans.create': can, 'permissions.read': can, 'policies.read': can },
    scoped_capabilities: { scope_kind: 'GUILD', scope_id: '*', capabilities: { 'structure.write': denyMove ? cannot : can } },
    bot_operations: {
      REORDER_CHANNELS: { ...can, operation: 'REORDER_CHANNELS', required_permissions: [] },
      CREATE_CHANNEL: { ...can, operation: 'CREATE_CHANNEL', required_permissions: [] },
      MANAGE_CHANNEL: { ...can, operation: 'MANAGE_CHANNEL', required_permissions: ['MANAGE_CHANNELS'] },
    },
    coverage: 'FULL', completeness: 'FULL', freshness: 'FRESH',
  }
}

async function installRoutes(page: Page, captured: Captured, options: RouteOptions = {}) {
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
    if (path === `/api/v1/guilds/${GUILD_A}/structure`) return route.fulfill({ json: options.structureAProvider?.() ?? structureA() })
    if (path === `/api/v1/guilds/${GUILD_B}/structure`) return route.fulfill({ json: structureB() })
    if (path === `/api/v1/guilds/${GUILD_A}/dashboard-capabilities`) return route.fulfill({ json: capabilities(GUILD_A, options.denyMove) })
    if (path === `/api/v1/guilds/${GUILD_B}/dashboard-capabilities`) return route.fulfill({ json: capabilities(GUILD_B) })
    if (path === `/api/v1/guilds/${GUILD_A}/logical-groups` && method === 'GET') return route.fulfill({ json: { guild_id: GUILD_A, resource_kind: 'DID_LOGICAL_RESOURCE', groups: [{ id: '11111111-2222-4333-8444-555555555555', guild_id: GUILD_A, name: 'Raid teams', slug: 'raid-teams', description: null, metadata_json: {}, resources: [] }] } })
    if (path === `/api/v1/guilds/${GUILD_A}/logical-groups/11111111-2222-4333-8444-555555555555` && method === 'PATCH') { captured.logicalGroupPatches?.push(request.postDataJSON() as LogicalGroupPatch); return route.fulfill({ status: 204 }) }
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

async function installSocketHarness(page: Page) {
  await page.addInitScript({ content: `
    (() => {
      const sockets = [];
      class DIDMockWebSocket {
        static CONNECTING = 0;
        static OPEN = 1;
        static CLOSING = 2;
        static CLOSED = 3;
        constructor(url) {
          this.url = String(url);
          this.readyState = DIDMockWebSocket.CONNECTING;
          this.onopen = null;
          this.onclose = null;
          this.onerror = null;
          this.onmessage = null;
          sockets.push(this);
          setTimeout(() => {
            this.readyState = DIDMockWebSocket.OPEN;
            if (this.onopen) this.onopen(new Event('open'));
          }, 0);
        }
        close(code = 1000) {
          this.readyState = DIDMockWebSocket.CLOSED;
          if (this.onclose) this.onclose({ code });
        }
      }
      window.WebSocket = DIDMockWebSocket;
      window.__didEmitGuildEvent = (event) => {
        const socket = sockets.at(-1);
        if (socket && socket.onmessage) socket.onmessage({ data: JSON.stringify(event) });
      };
    })();
  ` })
}

test('explorer renders faithful hierarchy, selection inspector, compact language control and survives reload', async ({ page }) => {
  const captured = { plans: [] as CapturedPlan[], logicalGroupPatches: [] as LogicalGroupPatch[] }
  await installRoutes(page, captured)
  await page.goto(`/guild/${GUILD_A}/structure`)

  await expect(page.getByRole('heading', { name: 'Discord structure' })).toBeVisible()
  await expect(page.getByText('2 categories')).toBeVisible()
  await expect(page.getByText('3 channels')).toBeVisible()
  await expect(page.getByText('1 threads')).toBeVisible()
  await expect(resourceRow(page, 'General')).toBeVisible()
  await expect(resourceRow(page, 'welcome')).toBeVisible()
  await expect(resourceRow(page, 'roadmap')).toBeVisible()
  await expect(page.getByRole('region', { name: 'DID logical groups' })).toContainText('Dashboard-only groupings; these are not Discord servers or categories.')
  await expect(page.getByText('Internal logical_group · raid-teams')).toBeVisible()
  await page.getByRole('button', { name: 'Edit label' }).click()
  await page.getByLabel('Logical group display label').fill('Raid squads')
  await page.getByLabel('Logical group display label').press('Enter')
  await expect.poll(() => captured.logicalGroupPatches).toEqual([{ name: 'Raid squads', description: null, metadata: {} }])
  expect(captured.logicalGroupPatches[0]).not.toHaveProperty('slug')
  expect(captured.logicalGroupPatches[0]).not.toHaveProperty('resources')
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

test('a slow second label click starts the canonical inline rename', async ({ page }) => {
  const captured = { plans: [] as CapturedPlan[] }
  await installRoutes(page, captured)
  await page.goto(`/guild/${GUILD_A}/structure`)

  const label = resourceRow(page, 'welcome').locator('.resource-copy')
  await label.click()
  await page.waitForTimeout(450)
  await label.click()
  const input = page.getByLabel('Discord resource name')
  await expect(input).toBeVisible()
  await input.fill('welcome-center')
  await input.press('Enter')

  await expect(page).toHaveURL(new RegExp(`/guild/${GUILD_A}/plans$`))
  expect(captured.plans[0]?.nodes?.[0]).toMatchObject({ discord_id: CHANNEL_WELCOME, resource_type: 'CHANNEL', properties: { name: 'welcome-center' } })
})

test('F2 starts the same inline rename and plan compiler path', async ({ page }) => {
  const captured = { plans: [] as CapturedPlan[] }
  await installRoutes(page, captured)
  await page.goto(`/guild/${GUILD_A}/structure`)

  const row = resourceRow(page, 'General')
  await row.click()
  await row.press('F2')
  await page.getByLabel('Discord resource name').fill('Community')
  await page.getByLabel('Discord resource name').press('Enter')

  expect(captured.plans[0]?.nodes?.[0]).toMatchObject({ discord_id: CAT_GENERAL, resource_type: 'CATEGORY', properties: { name: 'Community' } })
})

test('context-menu Rename starts the same inline rename and plan compiler path', async ({ page }) => {
  const captured = { plans: [] as CapturedPlan[] }
  await installRoutes(page, captured)
  await page.goto(`/guild/${GUILD_A}/structure`)

  await resourceRow(page, 'welcome').click({ button: 'right' })
  await page.getByRole('menuitem', { name: 'Rename' }).click()
  await page.getByLabel('Discord resource name').fill('welcome-desk')
  await page.getByLabel('Discord resource name').press('Enter')

  expect(captured.plans[0]?.nodes?.[0]).toMatchObject({ discord_id: CHANNEL_WELCOME, properties: { name: 'welcome-desk' } })
})

test('single-resource context menu prioritizes Manage access and preserves the exact scope', async ({ page }) => {
  const captured = { plans: [] as CapturedPlan[] }
  await installRoutes(page, captured)
  await page.goto(`/guild/${GUILD_A}/structure`)

  await resourceRow(page, 'welcome').click({ button: 'right' })
  const menu = page.getByRole('menu', { name: 'Available actions' })
  await expect(menu.getByRole('menuitem').first()).toHaveText('Manage access')
  await menu.getByRole('menuitem', { name: 'Manage access' }).click()

  await expect(page).toHaveURL(new RegExp(`/guild/${GUILD_A}/policies\\?targetType=CHANNEL&targetId=${CHANNEL_WELCOME}$`))
})

test('mixed category and channel selection offers only the preseeded bulk access action', async ({ page }) => {
  const captured = { plans: [] as CapturedPlan[] }
  await installRoutes(page, captured)
  await page.goto(`/guild/${GUILD_A}/structure`)

  await resourceRow(page, 'General').click()
  await resourceRow(page, 'welcome').click({ modifiers: ['Control'] })
  await page.locator('.structure-action-button').click()
  const menu = page.getByRole('menu', { name: 'Available actions' })
  await expect(menu.getByRole('menuitem')).toHaveCount(1)
  await menu.getByRole('menuitem', { name: 'Manage selected access' }).click()

  await expect(page).toHaveURL(new RegExp(`/guild/${GUILD_A}/matrix\\?resources=${CAT_GENERAL}%2C${CHANNEL_WELCOME}$`))
})

test('emoji picker and Unicode name round-trip unchanged into the validated plan', async ({ page }) => {
  const captured = { plans: [] as CapturedPlan[] }
  await installRoutes(page, captured)
  await page.goto(`/guild/${GUILD_A}/structure`)

  const row = resourceRow(page, 'welcome')
  await row.click()
  await row.press('F2')
  await page.getByRole('button', { name: 'Choose an emoji' }).click()
  await page.getByRole('button', { name: 'grinning face', exact: true }).click()
  const input = page.getByLabel('Discord resource name')
  await expect(input).toHaveValue('😀 welcome')
  await input.fill('📣 annonces-été')
  await input.press('Enter')

  expect(captured.plans[0]?.nodes?.[0]?.properties?.name).toBe('📣 annonces-été')
})

test('an invalid Discord name is blocked before any plan request', async ({ page }) => {
  const captured = { plans: [] as CapturedPlan[] }
  await installRoutes(page, captured)
  await page.goto(`/guild/${GUILD_A}/structure`)

  const row = resourceRow(page, 'welcome')
  await row.click()
  await row.press('F2')
  await page.getByLabel('Discord resource name').fill('a'.repeat(101))
  await expect(page.getByText('Discord names are limited to 100 characters.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Prepare rename' })).toBeDisabled()
  expect(captured.plans).toHaveLength(0)
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
  // Cross-server DnD is a desktop workbench interaction. Keep source and destination
  // simultaneously inside the viewport so the pointer path represents a real drag,
  // not an impossible move to coordinates below the browser viewport.
  await page.setViewportSize({ width: 1600, height: 1000 })
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

test('an impossible structure action is blocked and explains the missing capability', async ({ page }) => {
  const captured = { plans: [] as CapturedPlan[] }
  await installRoutes(page, captured, { denyMove: true })
  await page.goto(`/guild/${GUILD_A}/structure`)

  await resourceRow(page, 'welcome').click({ button: 'right' })
  const menu = page.getByRole('menu', { name: 'Available actions' })
  await expect(menu).toBeVisible()
  const move = menu.getByRole('menuitem', { name: 'Propose move' })
  await expect(move).toBeDisabled()
  await expect(move).toHaveAttribute('title', 'Required capability is missing.')
  expect(captured.plans).toHaveLength(0)
})

test('a live structure event reconciles an external Discord change without a full page reload', async ({ page }) => {
  await installSocketHarness(page)
  let currentStructure = structureA()
  const captured = { plans: [] as CapturedPlan[] }
  await installRoutes(page, captured, { structureAProvider: () => currentStructure })
  await page.goto(`/guild/${GUILD_A}/structure`)

  await expect(resourceRow(page, 'welcome')).toBeVisible()
  await expect(page.getByText('Live updates connected', { exact: true })).toBeVisible()

  currentStructure = {
    ...currentStructure,
    categories: currentStructure.categories.map((category) => category.id === CAT_GENERAL
      ? { ...category, channels: category.channels.map((item) => item.id === CHANNEL_WELCOME ? { ...item, name: 'welcome-renamed' } : item) }
      : category),
  }

  await page.evaluate((event) => {
    const emitter = (globalThis as unknown as { __didEmitGuildEvent?: (value: unknown) => void }).__didEmitGuildEvent
    emitter?.(event)
  }, { guild_id: GUILD_A, sequence: 1, version: 1, type: 'structure.updated' })

  await expect(resourceRow(page, 'welcome-renamed')).toBeVisible()
  await expect(resourceRow(page, 'welcome')).toHaveCount(0)
})
