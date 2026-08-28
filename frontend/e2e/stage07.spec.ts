import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

const A = '700000000000000001'; const B = '700000000000000002'; const USER = '700000000000000003'
const can = { outcome: 'CAN', causes: [], remediations: [] }
function capabilityPayload(guildId = A) { const user = { 'structure.read': can, 'structure.write': can, 'plans.create': can, 'permissions.read': can }; return { guild_id: guildId, source: 'AUTHORIZATION_AND_LOCAL_CACHE', discord_rest_calls: 0, user_capabilities: user, scoped_capabilities: { scope_kind: 'GUILD', scope_id: '*', capabilities: user }, bot_operations: { REORDER_CHANNELS: can, CREATE_CHANNEL: can }, coverage: 'FULL', completeness: 'FULL', freshness: 'FRESH' } }

async function mockDashboard(page: Page) {
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname; const method = route.request().method()
    if (path === '/api/v1/ui/locales') return route.fulfill({ json: { catalog_version: 'did-ui-v1', locales: [{ locale_code: 'en', display_name: 'English', flag_code: 'gb', direction: 'ltr' }, { locale_code: 'fr', display_name: 'Français', flag_code: 'fr', direction: 'ltr' }, { locale_code: 'de', display_name: 'Deutsch', flag_code: 'de', direction: 'ltr' }, { locale_code: 'es', display_name: 'Español', flag_code: 'es', direction: 'ltr' }] } })
    if (path.startsWith('/api/v1/ui/locales/')) return route.fulfill({ status: 404, json: { error: { code: 'NOT_FOUND', message_key: 'errors.resource.notFound', params: {}, request_id: 'e2e' } } })
    if (path === '/api/v1/me') return route.fulfill({ json: { authenticated: true, user: { discord_user_id: USER, username: 'owner', global_name: 'Owner' }, active_guild_id: A, csrf_token: 'csrf', policy_version: 1 } })
    if (path === '/api/v1/me/preferences') return route.fulfill({ json: method === 'GET' ? { ui_locale_override_code: null, timezone: null } : route.request().postDataJSON() })
    if (path === '/api/v1/guilds') return route.fulfill({ json: { guilds: [{ guild_id: A, name: 'Alpha', owner: true, permissions: '8', installation_status: 'ACTIVE' }, { guild_id: B, name: 'Beta', owner: true, permissions: '8', installation_status: 'ACTIVE' }] } })
    if (path.endsWith('/select')) return route.fulfill({ json: { guild_id: path.split('/')[4], csrf_token: 'next', policy_version: 2 } })
    if (path.endsWith('/structure')) {
      const guild = path.split('/')[4] ?? A; const category = `${guild.slice(0, -1)}4`
      return route.fulfill({ json: { guild_id: guild, source: 'LOCAL_CACHE', discord_rest_calls: 0, categories: [{ guild_id: guild, id: category, type: 4, name: 'Operations', position: 0, parent_id: null, resource_kind: 'DISCORD_RESOURCE', observability: 'VISIBLE', freshness: 'FRESH', data_assertion: 'CURRENT_CONFIRMED', channels: [{ guild_id: guild, id: `${guild.slice(0, -1)}5`, type: 0, name: 'general', position: 0, parent_id: category, resource_kind: 'DISCORD_RESOURCE', observability: 'VISIBLE', freshness: 'FRESH', data_assertion: 'CURRENT_CONFIRMED', threads: [] }] }], root_channels: [] } })
    }
    if (path.endsWith('/dashboard-capabilities')) return route.fulfill({ json: capabilityPayload(path.split('/')[4]) })
    if (/\/guilds\/[^/]+\/plans$/.test(path) && method === 'GET') return route.fulfill({ json: { guild_id: path.split('/')[4], plans: [{ id: '11111111-1111-4111-8111-111111111111', guild_id: path.split('/')[4], status: 'APPLYING', state_version: 3, plan_hash: 'a'.repeat(64), risk_level: 'MEDIUM', impact: {}, reinforced_confirmation_required: false, created_at: '2026-08-28T00:00:00Z', updated_at: '2026-08-28T00:00:00Z', error_code: null }] } })
    if (/\/guilds\/[^/]+\/plans$/.test(path) && method === 'POST') return route.fulfill({ status: 201, json: { created: true, plan: { id: '22222222-2222-4222-8222-222222222222', state_version: 1 } } })
    if (path.endsWith('/validate') && method === 'POST') return route.fulfill({ json: { plan: { id: '22222222-2222-4222-8222-222222222222', state_version: 2 }, preflight: { allowed: true, errors: [], warnings: [], checked_capabilities: ['MANAGE_CHANNELS'] } } })
    if (path.endsWith('/progress')) return route.fulfill({ json: { events: [{ sequence: 1, plan_status: 'APPLYING', completed_operations: 1, total_operations: 4, message_key: 'plans.progress.applying', params: {} }] } })
    if (path.endsWith('/permissions/explain') && method === 'POST') return route.fulfill({ json: { effective_bits: '1024', warnings: [], trace: [{ step: 'BASE_EVERYONE', reason_key: 'permissions.trace.baseEveryone', after: '1024' }], outcome: 'CAN' } })
    if (path === '/api/v1/transfers' && method === 'POST') return route.fulfill({ status: 201, json: { transfer: { status: 'COMPILED' }, plan: { id: '33333333-3333-4333-8333-333333333333' } } })
    return route.fulfill({ status: 404, json: { error: { code: 'NOT_FOUND', message_key: 'errors.resource.notFound', params: {}, request_id: 'e2e' } } })
  })
}

const localizedContextMenus: Record<string, string> = { en: 'Available actions', fr: 'Actions disponibles', de: 'Verfügbare Aktionen', es: 'Acciones disponibles' }
for (const locale of ['en', 'fr', 'de', 'es']) {
  test(`@a11y localized shell has no serious axe violation (${locale})`, async ({ page }) => {
    await mockDashboard(page)
    await page.route('**/api/v1/me/preferences', (route) => route.fulfill({ json: { ui_locale_override_code: locale, timezone: null } }))
    await page.goto(`/guild/${A}/structure`)
    await expect(page.getByRole('tree')).toBeVisible()
    await expect(page.locator('html')).toHaveAttribute('lang', locale)
    await page.locator('[data-drop-name="general"]').click({ button: 'right' })
    await expect(page.getByRole('menu', { name: localizedContextMenus[locale] })).toBeVisible()
    await page.keyboard.press('Escape')
    const results = await new AxeBuilder({ page }).exclude('.locale-flag').analyze()
    expect(results.violations.filter((item) => ['serious', 'critical'].includes(item.impact ?? ''))).toEqual([])
  })
}

test('context menu, command palette, locale and tenant switch stay coherent', async ({ page }) => {
  await mockDashboard(page); await page.goto(`/guild/${A}/structure`)
  const channel = page.locator('[data-drop-name="general"]')
  await channel.click(); await channel.click({ button: 'right' })
  await expect(page.getByRole('menu', { name: 'Available actions' })).toBeVisible()
  await page.keyboard.press('Escape'); await page.keyboard.press('Control+k')
  await expect(page.getByRole('dialog', { name: 'Command palette' })).toBeVisible()
  await page.keyboard.press('Escape'); await page.getByLabel('Interface language').selectOption('fr')
  await expect(page.getByRole('heading', { name: 'Structure Discord' })).toBeVisible()
  await page.getByLabel('Serveur actif').selectOption(B)
  await expect(page).toHaveURL(new RegExp(`/guild/${B}/structure$`)); await expect(page.locator('.topbar strong')).toHaveText('Beta')
})

test('mounted left drag creates a same-server DSG preview before any command', async ({ page }) => {
  await mockDashboard(page); await page.goto(`/guild/${A}/structure`)
  const request = page.waitForRequest((value) => value.url().endsWith(`/guilds/${A}/plans`) && value.method() === 'POST')
  await page.locator('[data-drop-name="general"]').dragTo(page.locator('[data-drop-name="Operations"] > .resource-name'))
  await expect(page.getByRole('dialog', { name: 'Review proposed action' })).toBeVisible(); await page.getByRole('button', { name: 'Preview' }).click()
  const body = (await request).postDataJSON(); expect(body.schema_version).toBe('did-dsg-v1'); expect(body.nodes[0]).toMatchObject({ discord_id: `${A.slice(0, -1)}5`, resource_type: 'CHANNEL', properties: { parent_id: `${A.slice(0, -1)}4` } })
})

test('mounted cross-server left drag preserves source and destination in transfer preview', async ({ page }) => {
  await mockDashboard(page); await page.goto(`/guild/${A}/structure`)
  await page.locator('[data-drop-name="general"]').dragTo(page.locator('[data-drop-name="Beta"]'))
  await expect(page.getByRole('dialog', { name: 'Review proposed action' })).toBeVisible(); await page.getByRole('button', { name: 'Preview' }).click()
  await expect(page).toHaveURL(new RegExp(`/guild/${A}/clone$`)); await expect(page.getByLabel('Discord resource ID')).toHaveValue(`${A.slice(0, -1)}5`); await expect(page.getByLabel('Destination server')).toHaveValue(B)
  const request = page.waitForRequest((value) => value.url().endsWith('/api/v1/transfers') && value.method() === 'POST'); await page.getByRole('button', { name: 'Preview' }).click()
  expect((await request).postDataJSON()).toMatchObject({ source_guild_id: A, destination_guild_id: B, selection: { artifact_type: 'CHANNEL', channel_ids: [`${A.slice(0, -1)}5`] }, mode: 'COPY_AS_NEW' })
})

test('right drag opens the localized drop action menu', async ({ page }) => {
  await mockDashboard(page); await page.goto(`/guild/${A}/structure`)
  const source = await page.locator('[data-drop-name="general"]').boundingBox(); const target = await page.locator('[data-drop-name="Beta"]').boundingBox(); if (!source || !target) throw new Error('drag coordinates unavailable')
  await page.mouse.move(source.x + 4, source.y + 4); await page.mouse.down({ button: 'right' }); await page.mouse.move(target.x + 4, target.y + 4, { steps: 4 }); await page.mouse.up({ button: 'right' })
  await expect(page.getByRole('menu', { name: 'Choose a drop action' })).toBeVisible()
})

test('tree roving tabindex supports ArrowDown', async ({ page }) => {
  await mockDashboard(page); await page.goto(`/guild/${A}/structure`)
  const category = page.locator('[data-drop-name="Operations"]'); const channel = page.locator('[data-drop-name="general"]'); await category.focus(); await page.keyboard.press('ArrowDown'); await expect(channel).toBeFocused(); await category.focus(); await page.keyboard.press('ArrowLeft'); await expect(category).toHaveAttribute('aria-expanded', 'false'); await expect(channel).toBeHidden(); await page.keyboard.press('ArrowRight'); await expect(category).toHaveAttribute('aria-expanded', 'true'); await expect(channel).toBeVisible()
})

test('context menu supports End and Enter keyboard navigation', async ({ page }) => {
  await mockDashboard(page); await page.goto(`/guild/${A}/structure`)
  await page.locator('[data-drop-name="general"]').click({ button: 'right' }); await page.keyboard.press('End'); await page.keyboard.press('Enter'); await expect(page).toHaveURL(new RegExp(`/guild/${A}/permissions$`))
})

test('dialog traps focus and restores it on Escape', async ({ page }) => {
  await mockDashboard(page); await page.goto(`/guild/${A}/structure`)
  const trigger = page.locator('.command-trigger'); await trigger.click(); const input = page.getByLabel('Search actions and pages'); await expect(input).toBeFocused(); await page.keyboard.press('Shift+Tab'); await expect(page.getByRole('button', { name: 'Close' })).toBeFocused(); await page.keyboard.press('Escape'); await expect(trigger).toBeFocused()
})

test('unknown or denied capability disables registry commands', async ({ page }) => {
  await mockDashboard(page)
  await page.route('**/api/v1/guilds/*/dashboard-capabilities*', (route) => { const user = { 'structure.write': { outcome: 'CANNOT', causes: ['capability.user.not_granted'], remediations: [] } }; return route.fulfill({ json: { guild_id: A, source: 'AUTHORIZATION_AND_LOCAL_CACHE', discord_rest_calls: 0, user_capabilities: user, scoped_capabilities: { scope_kind: 'GUILD', scope_id: '*', capabilities: user }, bot_operations: { REORDER_CHANNELS: { outcome: 'UNKNOWN', causes: ['cache.incomplete'], remediations: [] } }, coverage: 'PARTIAL', completeness: 'PARTIAL', freshness: 'STALE' } }) })
  await page.goto(`/guild/${A}/structure`); await page.locator('[data-drop-name="general"]').click({ button: 'right' }); const move = page.getByRole('menuitem', { name: 'Propose move' }); await expect(move).toBeDisabled(); await expect(move).toHaveAttribute('title', 'Required capability is missing.')
  await page.keyboard.press('Escape'); await page.keyboard.press('Control+k'); await expect(page.getByRole('dialog', { name: 'Command palette' })).toBeVisible(); await expect(page.getByRole('menuitem', { name: 'Propose move' })).toBeDisabled()
})

test('authenticated server locale preference hydrates the UI', async ({ page }) => {
  await mockDashboard(page); await page.route('**/api/v1/me/preferences', (route) => route.request().method() === 'GET' ? route.fulfill({ json: { ui_locale_override_code: 'fr', timezone: null } }) : route.continue())
  await page.goto(`/guild/${A}/structure`); await expect(page.locator('html')).toHaveAttribute('lang', 'fr'); await expect(page.getByRole('heading', { name: 'Structure Discord' })).toBeVisible()
})

test('plan progress uses backend counts and localized message keys', async ({ page }) => {
  await mockDashboard(page); await page.goto(`/guild/${A}/plans`); await page.locator('.plan-card').click(); await expect(page.getByText('Applying plan.')).toBeVisible(); await expect(page.locator('progress')).toHaveAttribute('value', '25'); await expect(page.getByText('plans.progress.applying', { exact: true })).toHaveCount(0)
})

test('Escape cancels an active pointer gesture without opening a preview', async ({ page }) => {
  await mockDashboard(page); await page.goto(`/guild/${A}/structure`); const source = page.locator('[data-drop-name="general"]'); const box = await source.boundingBox(); if (!box) throw new Error('drag coordinates unavailable'); await page.mouse.move(box.x + 3, box.y + 3); await page.mouse.down(); await page.mouse.move(box.x + 20, box.y + 3); await page.keyboard.press('Escape'); await page.mouse.up(); await expect(page.getByRole('dialog', { name: 'Review proposed action' })).toHaveCount(0); await expect(page.locator('[aria-live="polite"]').last()).toContainText('Drag cancelled.')
})

test('durable progress evolves from long-running counts to terminal success', async ({ page }) => {
  await mockDashboard(page); let calls = 0
  await page.route('**/api/v1/guilds/*/plans/*/progress', (route) => { calls += 1; const terminal = calls > 1; return route.fulfill({ json: { events: terminal ? [{ sequence: 1, plan_status: 'APPLYING', completed_operations: 1, total_operations: 4, message_key: 'plans.progress.applying', params: {} }, { sequence: 2, plan_status: 'SUCCEEDED', completed_operations: 4, total_operations: 4, message_key: 'plans.progress.succeeded', params: {} }] : [{ sequence: 1, plan_status: 'APPLYING', completed_operations: 1, total_operations: 4, message_key: 'plans.progress.applying', params: {} }] } }) })
  await page.goto(`/guild/${A}/plans`); await page.locator('.plan-card').click(); await expect(page.locator('progress')).toHaveAttribute('value', '25'); await expect(page.getByText('Plan applied and verified.')).toBeVisible({ timeout: 4_000 }); await expect(page.locator('progress')).toHaveAttribute('value', '100'); expect(calls).toBeGreaterThan(1)
})

test('terminal verification failure remains visible and is never shown as success', async ({ page }) => {
  await mockDashboard(page); await page.route('**/api/v1/guilds/*/plans/*/progress', (route) => route.fulfill({ json: { events: [{ sequence: 9, plan_status: 'VERIFICATION_FAILED', completed_operations: 4, total_operations: 4, message_key: 'plans.progress.verification_failed', params: {} }] } }))
  await page.goto(`/guild/${A}/plans`); await page.locator('.plan-card').click(); await expect(page.getByText('Verification failed.')).toBeVisible(); await expect(page.getByText('Plan applied and verified.')).toHaveCount(0)
})

test('keyboard command palette provides move and clone alternatives', async ({ page }) => {
  await mockDashboard(page); await page.goto(`/guild/${A}/structure`); await page.locator('[data-drop-name="general"]').click(); await page.keyboard.press('Control+k'); await page.getByRole('menuitem', { name: 'Propose move' }).click(); await expect(page.getByRole('dialog', { name: 'Review proposed action' })).toBeVisible(); await page.getByRole('button', { name: 'Close' }).click()
  await page.keyboard.press('Control+k'); await page.getByRole('menuitem', { name: 'Clone with dependencies' }).click(); await expect(page.getByRole('dialog', { name: 'Review proposed action' })).toBeVisible()
})

test('View As and Why Access submit the real permission explanation request', async ({ page }) => {
  await mockDashboard(page); await page.goto(`/guild/${A}/permissions`); await page.getByLabel('View as').selectOption('VIEW_AS_MEMBER'); await page.getByLabel('Discord subject ID').fill(USER); await page.getByLabel('Discord resource ID').fill(`${A.slice(0, -1)}5`)
  const request = page.waitForRequest((value) => value.url().endsWith(`/guilds/${A}/permissions/explain`) && value.method() === 'POST'); await page.getByRole('button', { name: 'Why access?' }).click(); expect((await request).postDataJSON()).toEqual({ view_as: 'VIEW_AS_MEMBER', subject_id: USER, role_id: null, resource_id: `${A.slice(0, -1)}5` }); await expect(page.getByText('Effective permissions: 1024')).toBeVisible()
})

test('backend 403 is final authority and refreshes the capability registry', async ({ page }) => {
  await mockDashboard(page); let forbidden = false
  await page.route('**/api/v1/guilds/*/dashboard-capabilities*', (route) => { const allowed = capabilityPayload(A); if (!forbidden) return route.fulfill({ json: allowed }); const denied = { outcome: 'CANNOT', causes: ['capability.user.not_granted'], remediations: [] }; return route.fulfill({ json: { ...allowed, user_capabilities: { ...allowed.user_capabilities, 'structure.write': denied }, scoped_capabilities: { scope_kind: 'GUILD', scope_id: '*', capabilities: { 'structure.write': denied } } } }) })
  await page.route(`**/api/v1/guilds/${A}/plans`, (route) => { if (route.request().method() !== 'POST') return route.fallback(); forbidden = true; return route.fulfill({ status: 403, json: { error: { code: 'AUTHORIZATION_DENIED', message_key: 'errors.authorization.denied', params: {}, request_id: 'drift' } } }) })
  await page.goto(`/guild/${A}/structure`); await page.locator('[data-drop-name="general"]').dragTo(page.locator('[data-drop-name="Operations"] > .resource-name')); await page.getByRole('button', { name: 'Preview' }).click(); await expect(page.getByRole('alert')).toHaveText('You are not allowed to perform this action.'); await expect(page).toHaveURL(new RegExp(`/guild/${A}/structure$`)); await page.getByRole('button', { name: 'Close' }).click(); await page.locator('[data-drop-name="general"]').click({ button: 'right' }); await expect(page.getByRole('menuitem', { name: 'Propose move' })).toBeDisabled()
})

test('an invalid active runtime catalog falls back atomically', async ({ page }) => {
  await mockDashboard(page); await page.route('**/api/v1/ui/locales', (route) => route.fulfill({ json: { locales: [{ locale_code: 'en', display_name: 'English', flag_code: 'gb', direction: 'ltr' }, { locale_code: 'it', display_name: 'Italiano', flag_code: 'it', direction: 'ltr' }] } })); await page.route('**/api/v1/ui/locales/it/catalog/*', (route) => route.fulfill({ json: { catalog_version: 'did-ui-v1', payload: { 'app.title': '<script>bad</script>' } } })); await page.route('**/api/v1/me/preferences', (route) => route.fulfill({ json: { ui_locale_override_code: 'it', timezone: null } }))
  await page.goto(`/guild/${A}/structure`); await expect(page.locator('html')).toHaveAttribute('lang', 'en'); await expect(page.getByRole('heading', { name: 'Discord structure' })).toBeVisible(); await expect(page.getByText('<script>bad</script>')).toHaveCount(0)
})
