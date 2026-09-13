import { expect, test, type Page, type Route } from '@playwright/test'

const USER = '700000000000000003'
const GUILD = '700000000000000001'

function me() {
  return {
    authenticated: true,
    user: { discord_user_id: USER, username: 'owner', global_name: 'Owner' },
    active_guild_id: null,
    csrf_token: 'csrf',
    policy_version: 1,
  }
}

async function commonRoute(route: Route, state: { active: boolean; imported: boolean; canBootstrap: boolean }) {
  const url = new URL(route.request().url())
  const path = url.pathname
  const method = route.request().method()

  if (path === '/api/v1/ui/locales') {
    return route.fulfill({ json: { catalog_version: 'did-ui-v2', locales: [] } })
  }
  if (path.startsWith('/api/v1/ui/locales/')) return route.fulfill({ status: 404, json: {} })
  if (path === '/api/v1/me') return route.fulfill({ json: me() })
  if (path === '/api/v1/me/preferences') return route.fulfill({ json: { ui_locale_override_code: null, timezone: null } })
  if (path === '/api/v1/guilds' && method === 'GET') {
    return route.fulfill({
      json: {
        guilds: [{
          guild_id: GUILD,
          name: 'Guild A',
          owner: state.canBootstrap,
          permissions: state.canBootstrap ? '8' : '0',
          installation_status: state.active ? 'ACTIVE' : 'PENDING_SETUP',
          dashboard_access: state.active,
          can_bootstrap: state.canBootstrap,
          blocked_reason: state.canBootstrap ? null : 'BOOTSTRAP_OWNER_OR_ADMINISTRATOR_REQUIRED',
        }],
      },
    })
  }
  if (path === `/api/v1/guilds/${GUILD}/select` && method === 'POST') {
    return route.fulfill({ json: { guild_id: GUILD, csrf_token: 'next-csrf', policy_version: 2 } })
  }
  if (path === `/api/v1/guilds/${GUILD}/onboarding` && method === 'GET') {
    return route.fulfill({ json: onboarding(state) })
  }
  if (path === `/api/v1/guilds/${GUILD}/onboarding/import` && method === 'POST') {
    state.imported = true
    return route.fulfill({ status: 202, json: { guild_id: GUILD, status: 'PENDING', job_id: '11111111-1111-4111-8111-111111111111' } })
  }
  if (path === `/api/v1/guilds/${GUILD}/onboarding/activate` && method === 'POST') {
    state.active = true
    return route.fulfill({ json: onboarding(state) })
  }
  if (path === `/api/v1/guilds/${GUILD}/dashboard-capabilities`) {
    return route.fulfill({ json: capabilities() })
  }
  if (path === `/api/v1/guilds/${GUILD}/structure`) {
    return route.fulfill({ json: { guild_id: GUILD, source: 'LOCAL_CACHE', discord_rest_calls: 0, categories: [], root_channels: [] } })
  }
  if (path === `/api/v1/guilds/${GUILD}/roles`) {
    return route.fulfill({ json: { guild_id: GUILD, source: 'LOCAL_CACHE', roles: [] } })
  }
  return route.fulfill({ status: 404, json: {} })
}

function onboarding(state: { active: boolean; imported: boolean; canBootstrap: boolean }) {
  return {
    guild_id: GUILD,
    name: 'Guild A',
    installation_status: state.active ? 'ACTIVE' : 'PENDING_SETUP',
    can_bootstrap: state.canBootstrap,
    bot_present: true,
    bot_user_id: '700000000000000009',
    configurator_verified: state.canBootstrap || state.active,
    structure_imported: state.imported,
    channel_count: state.imported ? 12 : 0,
    role_count: state.imported ? 5 : 0,
    coverage: state.imported ? 'FULL' : 'PARTIAL',
    freshness: 'FRESH',
    permissions_checked: state.imported,
    bot_operations: state.imported ? {
      CREATE_CHANNEL: { outcome: 'CAN', required_permissions: ['MANAGE_CHANNELS'], causes: [], remediations: [], warnings: [] },
      MANAGE_CHANNEL: { outcome: 'CANNOT', required_permissions: ['MANAGE_CHANNELS'], causes: ['capability.permission_missing.manage_channels'], remediations: ['capability.remediation.grant.manage_channels'], warnings: [] },
      MANAGE_ROLE: { outcome: 'UNKNOWN', required_permissions: ['MANAGE_ROLES'], causes: ['capability.target_role_required'], remediations: [], warnings: [] },
    } : {},
    initial_audit_complete: state.imported,
    dashboard_configuration_ready: true,
    ready_to_activate: !state.active && state.imported && state.canBootstrap,
    complete: state.active,
    blocked_reason: !state.canBootstrap ? 'BOOTSTRAP_OWNER_OR_ADMINISTRATOR_REQUIRED' : state.imported ? null : 'INITIAL_STRUCTURE_IMPORT_REQUIRED',
  }
}

function capabilities() {
  return {
    guild_id: GUILD,
    source: 'AUTHORIZATION_AND_LOCAL_CACHE',
    discord_rest_calls: 0,
    user_capabilities: {},
    scoped_capabilities: { scope_kind: 'GUILD', scope_id: '*', capabilities: {} },
    bot_operations: {},
    coverage: 'FULL',
    completeness: 'FULL',
    freshness: 'FRESH',
  }
}

async function installRoutes(page: Page, state: { active: boolean; imported: boolean; canBootstrap: boolean }) {
  await page.route('**/health/features', (route) => route.fulfill({ json: { features: { oauth: true, live_events: true, portability: false } } }))
  await page.route('**/api/v1/**', (route) => commonRoute(route, state))
}

test('pending Guild follows setup -> import -> activate -> overview', async ({ page }) => {
  const state = { active: false, imported: false, canBootstrap: true }
  await installRoutes(page, state)
  await page.goto('/guilds')

  await expect(page.getByRole('heading', { name: 'Guild A' })).toBeVisible()
  await page.getByRole('button', { name: 'Configure' }).click()
  await expect(page).toHaveURL(new RegExp(`/guild/${GUILD}/setup$`))
  await expect(page.getByRole('heading', { name: 'First server setup' })).toBeVisible()
  await expect(page.locator('.onboarding-step')).toHaveCount(9)

  await page.getByRole('button', { name: 'Import and verify structure' }).click()
  await expect(page.getByText('12 channels / threads · 5 roles')).toBeVisible()
  await expect(page.getByText('DID requests only the permissions needed by each function. ADMINISTRATOR is never required for convenience.')).toBeVisible()
  await expect(page.getByText('Missing Discord permission: MANAGE_CHANNELS.')).toBeVisible()
  await expect(page.getByText('A target role is required to check the role hierarchy.')).toBeVisible()
  await expect(page.locator('.onboarding-permission.cannot').getByText('Create, rename, move and configure Discord channels and categories.')).toBeVisible()
  await page.getByRole('button', { name: 'Activate this server' }).click()

  await expect(page).toHaveURL(new RegExp(`/guild/${GUILD}/overview$`))
  await expect(page.getByRole('heading', { name: 'Server overview' })).toBeVisible()
  await expect(page.getByText('Guild A').first()).toBeVisible()
  await expect(page.getByText('My library', { exact: true }).first()).toBeVisible()
})

test('non-admin sees a blocked setup with no executable action', async ({ page }) => {
  const state = { active: false, imported: false, canBootstrap: false }
  await installRoutes(page, state)
  await page.goto('/guilds')

  await expect(page.getByText('Setup requires the server owner or a Discord administrator.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Configure' })).toBeDisabled()
})
