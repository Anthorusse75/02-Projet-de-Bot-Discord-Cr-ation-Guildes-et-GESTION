import { expect, test, type Page } from '@playwright/test'

const USER = '700000000000000003'
const GUILD = '700000000000000001'

const can = { outcome: 'CAN', causes: [], remediations: [] }
const roles = [
  { id: '700000000000000010', name: 'Administrateur', position: 12, permissions: '8', known_flags: ['ADMINISTRATOR'], unknown_bits: '0', managed: false, freshness: 'FRESH' },
  { id: '700000000000000011', name: 'Co-fondateur', position: 11, permissions: '268435456', known_flags: ['MANAGE_ROLES', 'MANAGE_CHANNELS'], unknown_bits: '0', managed: false, freshness: 'FRESH' },
  { id: '700000000000000012', name: 'Responsable', position: 10, permissions: '32', known_flags: ['MANAGE_GUILD'], unknown_bits: '0', managed: false, freshness: 'FRESH' },
  { id: '700000000000000013', name: 'Modérateur', position: 9, permissions: '8192', known_flags: ['VIEW_CHANNEL', 'SEND_MESSAGES', 'MANAGE_MESSAGES', 'MODERATE_MEMBERS'], unknown_bits: '0', managed: false, freshness: 'FRESH' },
  { id: '700000000000000014', name: 'Aide-modérateur', position: 8, permissions: '3072', known_flags: ['VIEW_CHANNEL', 'SEND_MESSAGES'], unknown_bits: '0', managed: false, freshness: 'FRESH' },
  { id: '700000000000000015', name: 'Staff', position: 7, permissions: '1024', known_flags: ['VIEW_CHANNEL'], unknown_bits: '0', managed: false, freshness: 'FRESH' },
  { id: '700000000000000016', name: 'Membre confirmé', position: 6, permissions: '3072', known_flags: ['VIEW_CHANNEL', 'SEND_MESSAGES'], unknown_bits: '0', managed: false, freshness: 'FRESH' },
  { id: '700000000000000017', name: 'Nouveau membre', position: 5, permissions: '1024', known_flags: ['VIEW_CHANNEL'], unknown_bits: '0', managed: false, freshness: 'FRESH' },
  { id: GUILD, name: '@everyone', position: 0, permissions: '1024', known_flags: ['VIEW_CHANNEL'], unknown_bits: '0', managed: false, freshness: 'FRESH' },
  { id: '700000000000000018', name: 'DID Bot', position: 4, permissions: '268435456', known_flags: ['MANAGE_ROLES'], unknown_bits: '0', managed: true, freshness: 'FRESH' },
  { id: '700000000000000019', name: 'Bunny Translator', position: 3, permissions: '3072', known_flags: ['VIEW_CHANNEL', 'SEND_MESSAGES'], unknown_bits: '0', managed: true, freshness: 'FRESH' },
  { id: '700000000000000020', name: 'Ticket Tool', position: 2, permissions: '3072', known_flags: ['VIEW_CHANNEL', 'SEND_MESSAGES'], unknown_bits: '0', managed: true, freshness: 'FRESH' },
]

async function mockRoles(page: Page) {
  await page.route('**/health/features', (route) => route.fulfill({ json: { features: { oauth: true, live_events: true, portability: true } } }))
  await page.route('**/api/v1/**', (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    if (path === '/api/v1/ui/locales') return route.fulfill({ json: { catalog_version: 'did-ui-v2', locales: [] } })
    if (path.startsWith('/api/v1/ui/locales/')) return route.fulfill({ status: 404, json: {} })
    if (path === '/api/v1/me') return route.fulfill({ json: { authenticated: true, user: { discord_user_id: USER, username: 'anthorusse75', global_name: 'Anthorusse' }, active_guild_id: GUILD, csrf_token: 'csrf', policy_version: 1 } })
    if (path === '/api/v1/me/preferences') return route.fulfill({ json: { ui_locale_override_code: 'fr', timezone: null } })
    if (path === '/api/v1/guilds') return route.fulfill({ json: { guilds: [{ guild_id: GUILD, name: 'Serveur de la Communauté', owner: true, permissions: '8', installation_status: 'ACTIVE' }] } })
    if (path === `/api/v1/guilds/${GUILD}/roles`) return route.fulfill({ json: { guild_id: GUILD, source: 'LOCAL_CACHE', discord_rest_calls: 0, roles } })
    if (path === `/api/v1/guilds/${GUILD}/dashboard-capabilities`) return route.fulfill({ json: { guild_id: GUILD, source: 'AUTHORIZATION_AND_LOCAL_CACHE', discord_rest_calls: 0, user_capabilities: { 'roles.write': can, 'plans.create': can }, scoped_capabilities: { scope_kind: 'GUILD', scope_id: '*', capabilities: {} }, bot_operations: { CREATE_ROLE: can, MANAGE_ROLE: can, REORDER_ROLES: can }, coverage: 'FULL', completeness: 'FULL', freshness: 'FRESH' } })
    return route.fulfill({ status: 404, json: {} })
  })
}

test('UX1-T002 renders the canonical roles experience on desktop and mobile', async ({ page }) => {
  await mockRoles(page)
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto(`/guild/${GUILD}/roles`)
  await expect(page.getByRole('heading', { name: 'Rôles' })).toBeVisible()
  await expect(page.getByRole('option', { name: /Administrateur/ })).toBeVisible()
  await expect(page.getByText('Détails Discord')).toBeVisible()
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1)
  await page.screenshot({ path: 'test-results/ux1-t002-roles-desktop.png', fullPage: true })

  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: 'test-results/ux1-t002-roles-mobile-list.png', fullPage: false })
  await page.locator('.role-detail-canonical').scrollIntoViewIfNeeded()
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1)
  await page.screenshot({ path: 'test-results/ux1-t002-roles-mobile-detail.png', fullPage: false })
})
