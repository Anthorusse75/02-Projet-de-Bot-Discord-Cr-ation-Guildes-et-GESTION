import { expect, test, type Page } from '@playwright/test'

const USER = '700000000000000003'
const GUILD = '700000000000000001'
const BOT_ROLE = '700000000000000010'
const MOD_ROLE = '700000000000000011'
const MANAGED_ROLE = '700000000000000012'
const CAT = '700000000000000101'
const CHANNEL = '700000000000000201'
const MEMBER = '700000000000000301'
const PLAN = '11111111-1111-4111-8111-111111111111'

type PlanNode = { logical_key?: string; resource_type?: string; discord_id?: string; presence?: string; properties?: Record<string, unknown>; relations?: Array<Record<string, unknown>> }
type Harness = { plans: Array<{ nodes?: PlanNode[] }>; denyOverwrites?: boolean; adminWarning?: boolean }

function can() { return { outcome: 'CAN', causes: [], remediations: [] } }
function cannot(cause = 'capability.permission_missing.manage_roles') { return { outcome: 'CANNOT', causes: [cause], remediations: [] } }
function capabilities(harness: Harness, url: URL) {
  const targetRole = url.searchParams.get('target_role_id')
  const resource = url.searchParams.get('resource_id')
  const user = {
    'tenant.read': can(), 'roles.read': can(), 'roles.write': can(), 'permissions.read': can(), 'permissions.write': can(),
    'plans.create': can(), 'plans.apply': can(), 'bots.audit': can(), 'structure.read': can(), 'structure.write': can(),
  }
  const manageRole = targetRole === MANAGED_ROLE ? cannot('capability.hierarchy.target_managed') : can()
  return {
    guild_id: GUILD, source: 'AUTHORIZATION_AND_LOCAL_CACHE', discord_rest_calls: 0, user_capabilities: user,
    scoped_capabilities: { scope_kind: 'GUILD', scope_id: '*', capabilities: user },
    bot_operations: {
      CREATE_ROLE: can(), MANAGE_ROLE: manageRole, REORDER_ROLES: manageRole,
      MANAGE_OVERWRITES: resource && harness.denyOverwrites ? cannot() : can(),
      CREATE_CHANNEL: can(), MANAGE_CHANNEL: can(), REORDER_CHANNELS: can(), ASSIGN_ROLE: manageRole,
    }, coverage: 'FULL', completeness: 'FULL', freshness: 'FRESH',
  }
}

function roles() {
  return { guild_id: GUILD, source: 'LOCAL_CACHE', discord_rest_calls: 0, registry_version: 'discord-v1', roles: [
    { id: GUILD, name: '@everyone', position: 0, permissions: '1024', known_flags: ['VIEW_CHANNEL'], unknown_bits: '0', managed: false, freshness: 'FRESH' },
    { id: BOT_ROLE, name: 'DID Bot', position: 10, permissions: '268435456', known_flags: ['MANAGE_ROLES'], unknown_bits: '0', managed: true, freshness: 'FRESH' },
    { id: MANAGED_ROLE, name: 'Integration', position: 6, permissions: '1024', known_flags: ['VIEW_CHANNEL'], unknown_bits: '0', managed: true, freshness: 'FRESH' },
    { id: MOD_ROLE, name: 'Moderator', position: 5, permissions: '3072', known_flags: ['VIEW_CHANNEL', 'SEND_MESSAGES'], unknown_bits: '0', managed: false, freshness: 'FRESH' },
  ] }
}

function structure() {
  const base = { guild_id: GUILD, type: 0, position: 0, resource_kind: 'CHANNEL', observability: 'VISIBLE', freshness: 'FRESH', data_assertion: 'CURRENT_CONFIRMED', threads: [] }
  return { guild_id: GUILD, source: 'LOCAL_CACHE', discord_rest_calls: 0, categories: [{ ...base, id: CAT, type: 4, name: 'General', parent_id: null, channels: [{ ...base, id: CHANNEL, name: 'welcome', parent_id: CAT }] }], root_channels: [] }
}

function decision(harness: Harness) {
  return {
    guild_id: GUILD, subject_id: MOD_ROLE, resource_id: CHANNEL, calculated_bits: '3072', effective_bits: '3072', unknown_bits: '0',
    decision_status: 'COMPLETE', requested_permission: null, outcome: 'ALLOW', coverage: 'FULL', freshness: 'FRESH', incomplete_reasons: [],
    trace: [{ step: 'BASE_ROLE', source_type: 'ROLE', source_id: MOD_ROLE, allow_bits: '3072', deny_bits: '0', before: '1024', after: '3072', reason_key: 'permissions.trace.baseRole' }],
    implicit_denials: [], warnings: harness.adminWarning ? ['permissions.warning.administratorBypassesOverwrites'] : [], source_versions: [], registry_version: 'discord-v1', data_assertion: 'CURRENT_CONFIRMED',
  }
}

async function installRoutes(page: Page, harness: Harness) {
  await page.route('**/health/features', (route) => route.fulfill({ json: { features: { oauth: true, live_events: true, portability: true } } }))
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request(); const url = new URL(request.url()); const path = url.pathname; const method = request.method()
    if (path === '/api/v1/ui/locales') return route.fulfill({ json: { catalog_version: 'did-ui-v2', locales: [] } })
    if (path.startsWith('/api/v1/ui/locales/')) return route.fulfill({ status: 404, json: {} })
    if (path === '/api/v1/me') return route.fulfill({ json: { authenticated: true, user: { discord_user_id: USER, username: 'owner', global_name: 'Owner' }, active_guild_id: GUILD, csrf_token: 'csrf', policy_version: 1 } })
    if (path === '/api/v1/me/preferences') return route.fulfill({ json: { ui_locale_override_code: 'en', timezone: null } })
    if (path === '/api/v1/guilds' && method === 'GET') return route.fulfill({ json: { guilds: [{ guild_id: GUILD, name: 'Guild A', owner: true, permissions: '8', installation_status: 'ACTIVE' }] } })
    if (path === `/api/v1/guilds/${GUILD}/roles`) return route.fulfill({ json: roles() })
    if (path === `/api/v1/guilds/${GUILD}/structure`) return route.fulfill({ json: structure() })
    if (path === `/api/v1/guilds/${GUILD}/dashboard-capabilities`) return route.fulfill({ json: capabilities(harness, url) })
    if (path.endsWith('/permissions/explain') && method === 'POST') return route.fulfill({ json: decision(harness) })
    if (path.endsWith('/permissions/simple/compile') && method === 'POST') {
      const body = request.postDataJSON() as { concepts: string[] }
      const write = body.concepts.includes('WRITE')
      return route.fulfill({ json: { guild_id: GUILD, allow: write ? '3072' : '1024', deny: '0', known_flags: write ? ['SEND_MESSAGES', 'SEND_MESSAGES_IN_THREADS'] : ['VIEW_CHANNEL'], diagnostics: write ? ['permissions.simple.write_context_dependent'] : [], registry_version: 'discord-v1', persisted: false, discord_mutations: 0 } })
    }
    if (path.endsWith('/permissions/simulate') && method === 'POST') return route.fulfill({ json: { subjects: [{ subject_id: MEMBER, before: decision(harness), after: { ...decision(harness), effective_bits: '4096' }, added_effective_permissions: '1024', removed_effective_permissions: '2048' }], incomplete_subject_ids: [], warnings: [], persisted: false, discord_mutations: 0 } })
    if (path === `/api/v1/guilds/${GUILD}/plans` && method === 'POST') {
      const body = request.postDataJSON() as { nodes?: PlanNode[] }; harness.plans.push(body)
      return route.fulfill({ json: { created: true, plan: { id: PLAN, state_version: 1, status: 'DRAFT' } } })
    }
    if (path === `/api/v1/guilds/${GUILD}/plans/${PLAN}/validate` && method === 'POST') return route.fulfill({ json: { plan: { id: PLAN, state_version: 2, status: 'VALIDATED' }, preflight: { allowed: true, errors: [], warnings: [] } } })
    if (path === `/api/v1/guilds/${GUILD}/plans` && method === 'GET') return route.fulfill({ json: { guild_id: GUILD, plans: [] } })
    return route.fulfill({ status: 404, json: {} })
  })
}

async function openRole(page: Page, name = 'Moderator') {
  await page.getByRole('option', { name: new RegExp(name) }).click()
}

test('role hierarchy prepares create, rename, reorder and delete as validated plans without direct Discord mutation', async ({ page }) => {
  const harness: Harness = { plans: [] }; await installRoutes(page, harness)
  await page.goto(`/guild/${GUILD}/roles`)
  await expect(page.getByRole('heading', { name: 'Roles' })).toBeVisible()
  await expect(page.getByRole('group', { name: 'Filter roles' })).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Search for a role' })).toBeVisible()

  await page.getByRole('button', { name: 'Create role' }).click()
  await page.getByLabel('Role name').fill('Support')
  await page.getByRole('button', { name: 'Prepare proposal' }).click()
  await expect(page).toHaveURL(new RegExp(`/guild/${GUILD}/plans$`))

  await page.goto(`/guild/${GUILD}/roles`); await openRole(page)
  await page.getByRole('button', { name: 'Rename role' }).click(); await page.getByLabel('Role name').fill('Moderators'); await page.getByRole('button', { name: 'Prepare proposal' }).click()
  await page.goto(`/guild/${GUILD}/roles`); await openRole(page)
  await page.getByRole('button', { name: 'Move up' }).click(); await page.getByRole('button', { name: 'Prepare proposal' }).click()
  await page.goto(`/guild/${GUILD}/roles`); await openRole(page)
  await page.getByRole('button', { name: 'Delete role' }).click(); await page.getByRole('button', { name: 'Prepare proposal' }).click()

  expect(harness.plans).toHaveLength(4)
  expect(harness.plans[0]?.nodes?.[0]).toMatchObject({ resource_type: 'ROLE', properties: { name: 'Support', permissions: '0' } })
  expect(harness.plans[1]?.nodes?.[0]).toMatchObject({ resource_type: 'ROLE', discord_id: MOD_ROLE, properties: { name: 'Moderators' } })
  expect(harness.plans[2]?.nodes?.[0]).toMatchObject({ resource_type: 'ROLE', discord_id: MOD_ROLE, properties: { position: 6 } })
  expect(harness.plans[3]?.nodes?.[0]).toMatchObject({ resource_type: 'ROLE', discord_id: MOD_ROLE, presence: 'ABSENT' })
})

test('simple mode compiles human intentions into a real overwrite and previews impact before creating the plan', async ({ page }) => {
  const harness: Harness = { plans: [] }; await installRoutes(page, harness)
  await page.goto(`/guild/${GUILD}/permissions`)
  await page.getByLabel('Discord resource').selectOption(CHANNEL)
  await page.getByLabel('Discord role').selectOption(MOD_ROLE)
  await page.getByRole('group', { name: 'See this resource' }).getByRole('button', { name: 'Allow' }).click()
  await page.getByRole('group', { name: 'Write / send messages' }).getByRole('button', { name: 'Deny' }).click()
  await page.getByRole('button', { name: 'Preview impact' }).click()
  await expect(page.getByText('Allow: VIEW_CHANNEL')).toBeVisible()
  await expect(page.getByText(/Deny: SEND_MESSAGES/)).toBeVisible()
  await expect(page.getByText('Bot can manage overwrites here')).toBeVisible()
  await page.getByRole('button', { name: 'Prepare permission proposal' }).click()
  await expect(page).toHaveURL(new RegExp(`/guild/${GUILD}/plans$`))

  expect(harness.plans).toHaveLength(1)
  expect(harness.plans[0]?.nodes?.[0]).toMatchObject({ resource_type: 'OVERWRITE', properties: { target_type: 0, allow: '1024', deny: '3072' } })
  expect(harness.plans[0]?.nodes?.[0]?.relations).toEqual(expect.arrayContaining([
    { name: 'channel', kind: 'DISCORD_ID', value: CHANNEL }, { name: 'subject', kind: 'DISCORD_ID', value: MOD_ROLE },
  ]))
})

test('expert mode exposes the real Discord resolution trace and ADMINISTRATOR bypass warning', async ({ page }) => {
  const harness: Harness = { plans: [], adminWarning: true }; await installRoutes(page, harness)
  await page.goto(`/guild/${GUILD}/permissions`)
  await page.getByLabel('Discord resource').selectOption(CHANNEL)
  await page.getByLabel('Discord role').selectOption(MOD_ROLE)
  await page.getByRole('tab', { name: 'Expert mode' }).click()
  await page.getByRole('button', { name: 'Why this access?' }).click()
  await expect(page.getByText('Discord resolution trace')).toBeVisible()
  await expect(page.getByText('ADMINISTRATOR bypasses channel overwrites. This access cannot be restricted here.')).toBeVisible()
  await expect(page.getByText('3072', { exact: true }).first()).toBeVisible()
})

test('missing bot overwrite capability blocks a permission mutation before any plan is created', async ({ page }) => {
  const harness: Harness = { plans: [], denyOverwrites: true }; await installRoutes(page, harness)
  await page.goto(`/guild/${GUILD}/permissions`)
  await page.getByLabel('Discord resource').selectOption(CHANNEL)
  await page.getByLabel('Discord role').selectOption(MOD_ROLE)
  await page.getByRole('group', { name: 'See this resource' }).getByRole('button', { name: 'Allow' }).click()
  await page.getByRole('button', { name: 'Preview impact' }).click()
  const propose = page.getByRole('button', { name: 'Prepare permission proposal' })
  await expect(propose).toBeDisabled()
  await expect(page.getByText('The Discord bot cannot safely perform this change.')).toBeVisible()
  expect(harness.plans).toHaveLength(0)
})
