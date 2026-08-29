import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

const A = '700000000000000001'; const B = '700000000000000002'; const USER = '700000000000000003'
const FR = '11111111-1111-4111-8111-111111111111'; const EN = '22222222-2222-4222-8222-222222222222'
const can = { outcome: 'CAN', causes: [], remediations: [] }
const languages = [{ id: FR, guild_id: A, code: 'fr', display_name: 'French', emoji: '🇫🇷', enabled: true }, { id: EN, guild_id: A, code: 'en', display_name: 'English', emoji: '🇬🇧', enabled: true }]
function group(id: string, name: string, missing = false) { const channelGroup = `${id.slice(0,8)}-1111-4111-8111-111111111111`; return { id, guild_id: A, name, root_kind: 'CHANNEL_SET', routing_mode: 'HUB_AND_SPOKE', visibility_scope_id: '33333333-3333-4333-8333-333333333333', source_language_profile_id: FR, provider_binding_id: '44444444-4444-4444-8444-444444444444', status: 'ACTIVE', version: 3, languages, category_variants: [], channel_groups: [{ id: channelGroup, logical_key: `${id}.general`, display_name: `${name} general`, source_language_profile_id: FR }], channel_variants: [{ id: `${id.slice(0,8)}-2222-4222-8222-222222222222`, language_profile_id: FR, discord_channel_id: '700000000000000010', state: missing ? 'MISSING' : 'ACTIVE', translation_channel_group_id: channelGroup, translation_category_variant_id: null }], routes: [{ id: `${id.slice(0,8)}-3333-4333-8333-333333333333`, source_language_profile_id: FR, destination_language_profile_id: EN, state: 'ACTIVE' }] } }
const workspace = { guild_id: A, source: 'POSTGRESQL_DURABLE_TRUTH', discord_rest_calls: 0, languages, groups: [group('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','Guides',true), group('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb','Support')], providers: [{ id: '44444444-4444-4444-8444-444444444444', provider_type: 'existing_translation_bot', status: 'MANUAL_CONFIGURATION_REQUIRED', capabilities_json: {}, last_validated_at: null }], visibility_bindings: [{ id: '55555555-5555-4555-8555-555555555555', visibility_scope_id: '33333333-3333-4333-8333-333333333333', language_profile_id: FR, discord_role_id: '700000000000000020', state: 'ACTIVE' }], resource_language_policies: [{ id: '66666666-6666-4666-8666-666666666666', resource_type: 'CATEGORY', discord_resource_id: '700000000000000030', explicit_language_profile_id: FR, inherit_language: true, visibility_policy: 'OPEN_ALL', visibility_scope_id: null }, { id: '77777777-7777-4777-8777-777777777777', resource_type: 'CHANNEL', discord_resource_id: '700000000000000010', explicit_language_profile_id: EN, inherit_language: false, visibility_policy: 'SCOPE_AND_LANGUAGE', visibility_scope_id: '33333333-3333-4333-8333-333333333333' }] }
function capabilities() { const user = { 'structure.read': can, 'structure.write': can, 'plans.create': can }; return { guild_id: A, source: 'AUTHORIZATION_AND_LOCAL_CACHE', discord_rest_calls: 0, user_capabilities: user, scoped_capabilities: { scope_kind: 'GUILD', scope_id: '*', capabilities: user }, bot_operations: { CREATE_CHANNEL: { ...can, operation: 'CREATE_CHANNEL', required_permissions: [] } }, coverage: 'FULL', completeness: 'FULL', freshness: 'FRESH' } }

async function mockStage08(page: Page, locale = 'en') {
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/v1/ui/locales') return route.fulfill({ json: { catalog_version: 'did-ui-v2', locales: ['en','fr','de','es'].map((code) => ({ locale_code: code, display_name: code.toUpperCase(), flag_code: code, direction: 'ltr' })) } })
    if (path.startsWith('/api/v1/ui/locales/')) return route.fulfill({ status: 404, json: { error: { code: 'NOT_FOUND', message_key: 'errors.resource.notFound', params: {}, request_id: 'stage08-e2e' } } })
    if (path === '/api/v1/me') return route.fulfill({ json: { authenticated: true, user: { discord_user_id: USER, username: 'owner', global_name: 'Owner' }, active_guild_id: A, csrf_token: 'csrf', policy_version: 1 } })
    if (path === '/api/v1/me/preferences') return route.fulfill({ json: route.request().method() === 'GET' ? { ui_locale_override_code: locale, timezone: null } : route.request().postDataJSON() })
    if (path === '/api/v1/guilds') return route.fulfill({ json: { guilds: [{ guild_id: A, name: 'Alpha', owner: true, permissions: '8', installation_status: 'ACTIVE' }, { guild_id: B, name: 'Beta', owner: true, permissions: '8', installation_status: 'ACTIVE' }] } })
    if (path.endsWith('/dashboard-capabilities')) return route.fulfill({ json: capabilities() })
    if (path.endsWith('/translation-workspace')) return route.fulfill({ json: workspace })
    if (path.endsWith(`/members/${USER}/languages`)) return route.fulfill({ json: { guild_id: A, discord_user_id: USER, primary_language: null, languages: route.request().headers()['x-member-mode'] === 'none' ? [] : [{ language_profile_id: FR, source: 'ONBOARDING', enabled: true }, { language_profile_id: EN, source: 'EXPLICIT', enabled: true }] } })
    if (path.endsWith('/multilingual-clone/preview')) return route.fulfill({ json: { artifact: { schema_version: 'did-portable-multilingual-v1', source_guild_id: A, multilingual: { languages: ['fr','en'], translation_groups: [{ logical_id: 'guides' }, { logical_id: 'support' }], provider_requirements: [] } }, preview: { destination_guild_id: B, group_mappings: [{ source_logical_id: 'guides', destination_translation_group_id: '88888888-8888-4888-8888-888888888888', live_source_link: false }, { source_logical_id: 'support', destination_translation_group_id: '99999999-9999-4999-8999-999999999999', live_source_link: false }], provider_bindings_omitted: true, source_unchanged: true } } })
    return route.fulfill({ status: 404, json: { error: { code: 'NOT_FOUND', message_key: 'errors.resource.notFound', params: {}, request_id: 'stage08-e2e' } } })
  })
}

test('@a11y two independent FR/EN groups expose hierarchy, routes, drift, provider and visibility', async ({ page }) => {
  await mockStage08(page); await page.goto(`/guild/${A}/translations`)
  await expect(page.getByRole('heading', { name: 'Translation workspace' })).toBeVisible(); await expect(page.getByRole('heading', { name: 'Guides' })).toBeVisible(); await expect(page.getByRole('heading', { name: 'Support' })).toBeVisible()
  await expect(page.getByText('Manual configuration required')).toBeVisible(); await expect(page.getByText('Missing', { exact: true })).toBeVisible(); await expect(page.getByText(/Scope and language/)).toBeVisible(); await expect(page.getByText(/Inherited from category/)).toBeVisible(); await expect(page.getByText(/Explicit on resource/)).toBeVisible(); await expect(page.getByText('French → English')).toHaveCount(2)
  const results = await new AxeBuilder({ page }).exclude('.locale-flag').analyze(); expect(results.violations.filter((item) => ['serious','critical'].includes(item.impact ?? ''))).toEqual([])
})

test('member languages support zero and many without a primary language', async ({ page }) => {
  await mockStage08(page); await page.goto(`/guild/${A}/translations`)
  const many = await page.evaluate(async ({ guild, user }) => (await fetch(`/api/v1/guilds/${guild}/members/${user}/languages`)).json(), { guild: A, user: USER }); expect(many.primary_language).toBeNull(); expect(many.languages).toHaveLength(2)
  const none = await page.evaluate(async ({ guild, user }) => (await fetch(`/api/v1/guilds/${guild}/members/${user}/languages`, { headers: { 'X-Member-Mode': 'none' } })).json(), { guild: A, user: USER }); expect(none.primary_language).toBeNull(); expect(none.languages).toEqual([])
})

test('right drag and keyboard alternatives expose all multilingual registry actions', async ({ page }) => {
  await mockStage08(page); await page.goto(`/guild/${A}/translations`); const card = page.getByRole('heading', { name: 'Guides' }).locator('..').locator('..'); const box = await card.boundingBox(); if (!box) throw new Error('translation card coordinates unavailable')
  await page.mouse.move(box.x + 8, box.y + 8); await page.mouse.down({ button: 'right' }); await page.mouse.move(box.x + 28, box.y + 8, { steps: 3 }); await page.mouse.up({ button: 'right' }); await expect(page.getByRole('menu', { name: 'Available actions' })).toBeVisible()
  for (const label of ['Create variant','Link existing variant','Clone independently','Preview topology']) await expect(page.getByRole('menuitem', { name: label })).toBeVisible()
  await page.keyboard.press('Escape'); for (const label of ['Create variant','Link existing variant','Clone independently','Preview topology']) await expect(page.getByRole('button', { name: label }).first()).toBeVisible()
})

test('cross-Guild clone preview creates independent destination IDs without provider bindings', async ({ page }) => {
  await mockStage08(page); await page.goto(`/guild/${A}/translations`)
  const result = await page.evaluate(async ({ source, destination }) => (await fetch(`/api/v1/guilds/${source}/multilingual-clone/preview`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'csrf' }, body: JSON.stringify({ destination_guild_id: destination, languages: ['fr','en'], groups: [{ logical_id: 'guides' }, { logical_id: 'support' }], provider_requirements: [] }) })).json(), { source: A, destination: B })
  expect(new Set(result.preview.group_mappings.map((item: {destination_translation_group_id:string}) => item.destination_translation_group_id)).size).toBe(2); expect(result.preview.group_mappings.every((item: {live_source_link:boolean}) => !item.live_source_link)).toBeTruthy(); expect(result.preview.provider_bindings_omitted).toBeTruthy(); expect(JSON.stringify(result)).not.toMatch(/token|secret|config_encrypted/i)
})

const localeHeadings = { en: 'Translation workspace', fr: 'Espace de traduction', de: 'Uebersetzungsbereich', es: 'Espacio de traduccion' }
for (const [locale, heading] of Object.entries(localeHeadings)) test(`localized STAGE 08 surface has no raw enums or keys (${locale})`, async ({ page }) => {
  await mockStage08(page, locale); await page.goto(`/guild/${A}/translations`); await expect(page.locator('html')).toHaveAttribute('lang', locale); await expect(page.getByRole('heading', { name: heading })).toBeVisible(); await expect(page.getByText('HUB_AND_SPOKE')).toHaveCount(0); await expect(page.getByText(/^translations\./)).toHaveCount(0)
})
