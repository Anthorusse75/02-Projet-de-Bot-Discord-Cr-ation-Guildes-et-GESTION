import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

const A = '700000000000000001'; const B = '700000000000000002'; const USER = '700000000000000003'

async function mockDashboard(page: Page) {
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.startsWith('/api/v1/ui/locales/')) return route.fulfill({ status: 404, json: { error: { code: 'NOT_FOUND', message_key: 'errors.resource.notFound', params: {}, request_id: 'e2e' } } })
    if (path === '/api/v1/me') return route.fulfill({ json: { authenticated: true, user: { discord_user_id: USER, username: 'owner', global_name: 'Owner' }, active_guild_id: A, csrf_token: 'csrf', policy_version: 1 } })
    if (path === '/api/v1/guilds') return route.fulfill({ json: { guilds: [{ guild_id: A, name: 'Alpha', owner: true, permissions: '8', installation_status: 'ACTIVE' }, { guild_id: B, name: 'Beta', owner: true, permissions: '8', installation_status: 'ACTIVE' }] } })
    if (path.endsWith('/select')) return route.fulfill({ json: { guild_id: path.split('/')[4], csrf_token: 'next', policy_version: 2 } })
    if (path.endsWith('/structure')) {
      const guild = path.split('/')[4] ?? A; const category = `${guild.slice(0, -1)}4`
      return route.fulfill({ json: { guild_id: guild, source: 'LOCAL_CACHE', discord_rest_calls: 0, categories: [{ guild_id: guild, id: category, type: 4, name: 'Operations', position: 0, parent_id: null, resource_kind: 'DISCORD_RESOURCE', observability: 'VISIBLE', freshness: 'FRESH', data_assertion: 'CURRENT_CONFIRMED', channels: [{ guild_id: guild, id: `${guild.slice(0, -1)}5`, type: 0, name: 'general', position: 0, parent_id: category, resource_kind: 'DISCORD_RESOURCE', observability: 'VISIBLE', freshness: 'FRESH', data_assertion: 'CURRENT_CONFIRMED', threads: [] }] }], root_channels: [] } })
    }
    return route.fulfill({ status: 404, json: { error: { code: 'NOT_FOUND', message_key: 'errors.resource.notFound', params: {}, request_id: 'e2e' } } })
  })
}

for (const locale of ['en', 'fr', 'de', 'es']) {
  test(`@a11y localized shell has no serious axe violation (${locale})`, async ({ page }) => {
    await mockDashboard(page)
    await page.addInitScript((value) => localStorage.setItem('did.uiLocaleOverride', value), locale)
    await page.goto(`/guild/${A}/structure`)
    await expect(page.getByRole('tree')).toBeVisible()
    await expect(page.locator('html')).toHaveAttribute('lang', locale)
    const results = await new AxeBuilder({ page }).exclude('.locale-flag').analyze()
    expect(results.violations.filter((item) => ['serious', 'critical'].includes(item.impact ?? ''))).toEqual([])
  })
}

test('context menu, command palette, locale and tenant switch stay coherent', async ({ page }) => {
  await mockDashboard(page); await page.goto(`/guild/${A}/structure`)
  const channel = page.getByRole('treeitem', { name: /^# general$/ })
  await channel.click(); await channel.click({ button: 'right' })
  await expect(page.getByRole('menu', { name: 'Available actions' })).toBeVisible()
  await page.keyboard.press('Escape'); await page.keyboard.press('Control+k')
  await expect(page.getByRole('dialog', { name: 'Command palette' })).toBeVisible()
  await page.keyboard.press('Escape'); await page.getByLabel('Interface language').selectOption('fr')
  await expect(page.getByRole('heading', { name: 'Structure Discord' })).toBeVisible()
  await page.getByLabel('Serveur actif').selectOption(B)
  await expect(page).toHaveURL(new RegExp(`/guild/${B}/structure$`)); await expect(page.locator('.topbar strong')).toHaveText('Beta')
})
