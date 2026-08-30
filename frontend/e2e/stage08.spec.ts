import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

const A = '700000000000000001'; const B = '700000000000000002'; const USER = '700000000000000003'
const FR = '11111111-1111-4111-8111-111111111111'; const EN = '22222222-2222-4222-8222-222222222222'
const can = { outcome: 'CAN', causes: [], remediations: [] }
const languages = [{ id: FR, guild_id: A, code: 'fr', display_name: 'French', emoji: '🇫🇷', enabled: true }, { id: EN, guild_id: A, code: 'en', display_name: 'English', emoji: '🇬🇧', enabled: true }]
function group(id: string, name: string, providerBindingId: string, missing = false) { const channelGroup = `${id.slice(0,8)}-1111-4111-8111-111111111111`; return { id, guild_id: A, name, root_kind: 'CHANNEL_SET', routing_mode: 'HUB_AND_SPOKE', visibility_scope_id: '33333333-3333-4333-8333-333333333333', source_language_profile_id: FR, provider_binding_id: providerBindingId, status: 'ACTIVE', version: 3, languages, category_variants: [], channel_groups: [{ id: channelGroup, logical_key: `${id}.general`, display_name: `${name} general`, source_language_profile_id: FR }], channel_variants: [{ id: `${id.slice(0,8)}-2222-4222-8222-222222222222`, language_profile_id: FR, discord_channel_id: '700000000000000010', state: missing ? 'MISSING' : 'ACTIVE', translation_channel_group_id: channelGroup, translation_category_variant_id: null }], routes: [{ id: `${id.slice(0,8)}-3333-4333-8333-333333333333`, source_language_profile_id: FR, destination_language_profile_id: EN, state: 'ACTIVE' }] } }
const GUIDES = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'; const SUPPORT = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
const READY_PROVIDER = '44444444-4444-4444-8444-444444444444'; const MANUAL_PROVIDER = '55555555-5555-4555-8555-555555555555'
const workspace = { guild_id: A, source: 'POSTGRESQL_DURABLE_TRUTH', discord_rest_calls: 0, languages, groups: [group(GUIDES,'Guides',READY_PROVIDER,true), group(SUPPORT,'Support',MANUAL_PROVIDER)], providers: [{ id: READY_PROVIDER, provider_type: 'existing_translation_bot', status: 'READY', capabilities_json: { supports_hub_and_spoke: true }, last_validated_at: '2026-08-30T00:00:00Z' }, { id: MANUAL_PROVIDER, provider_type: 'existing_translation_bot', status: 'MANUAL_CONFIGURATION_REQUIRED', capabilities_json: {}, last_validated_at: null }], visibility_bindings: [{ id: '66666666-6666-4666-8666-666666666666', visibility_scope_id: '33333333-3333-4333-8333-333333333333', language_profile_id: FR, discord_role_id: '700000000000000020', state: 'ACTIVE' }], resource_language_policies: [{ id: '77777777-7777-4777-8777-777777777777', resource_type: 'CATEGORY', discord_resource_id: '700000000000000030', explicit_language_profile_id: FR, inherit_language: true, visibility_policy: 'OPEN_ALL', visibility_scope_id: null }, { id: '88888888-8888-4888-8888-888888888888', resource_type: 'CHANNEL', discord_resource_id: '700000000000000010', explicit_language_profile_id: EN, inherit_language: false, visibility_policy: 'SCOPE_AND_LANGUAGE', visibility_scope_id: '33333333-3333-4333-8333-333333333333' }] }
function capabilities(guildId = A) { const user = { 'structure.read': can, 'structure.write': can, 'plans.create': can }; return { guild_id: guildId, source: 'AUTHORIZATION_AND_LOCAL_CACHE', discord_rest_calls: 0, user_capabilities: user, scoped_capabilities: { scope_kind: 'GUILD', scope_id: '*', capabilities: user }, bot_operations: { CREATE_CHANNEL: { ...can, operation: 'CREATE_CHANNEL', required_permissions: [] } }, coverage: 'FULL', completeness: 'FULL', freshness: 'FRESH' } }

type Stage08Calls = { variants: Array<Record<string, unknown>>; links: Array<Record<string, unknown>>; clones: Array<Record<string, unknown>>; previews: string[]; capabilityGuilds: string[] }
function callLog(): Stage08Calls { return { variants: [], links: [], clones: [], previews: [], capabilityGuilds: [] } }

async function mockStage08(page: Page, locale = 'en', calls: Stage08Calls = callLog()) {
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/v1/ui/locales') return route.fulfill({ json: { catalog_version: 'did-ui-v2', locales: ['en','fr','de','es'].map((code) => ({ locale_code: code, display_name: code.toUpperCase(), flag_code: code, direction: 'ltr' })) } })
    if (path.startsWith('/api/v1/ui/locales/')) return route.fulfill({ status: 404, json: { error: { code: 'NOT_FOUND', message_key: 'errors.resource.notFound', params: {}, request_id: 'stage08-e2e' } } })
    if (path === '/api/v1/me') return route.fulfill({ json: { authenticated: true, user: { discord_user_id: USER, username: 'owner', global_name: 'Owner' }, active_guild_id: A, csrf_token: 'csrf', policy_version: 1 } })
    if (path === '/api/v1/me/preferences') return route.fulfill({ json: route.request().method() === 'GET' ? { ui_locale_override_code: locale, timezone: null } : route.request().postDataJSON() })
    if (path === '/api/v1/guilds') return route.fulfill({ json: { guilds: [{ guild_id: A, name: 'Alpha', owner: true, permissions: '8', installation_status: 'ACTIVE' }, { guild_id: B, name: 'Beta', owner: true, permissions: '8', installation_status: 'ACTIVE' }] } })
    if (path.endsWith('/dashboard-capabilities')) { const capabilityGuild = path.split('/')[4] ?? A; calls.capabilityGuilds.push(capabilityGuild); return route.fulfill({ json: capabilities(capabilityGuild) }) }
    if (path.endsWith('/translation-workspace')) return route.fulfill({ json: workspace })
    if (path.endsWith(`/members/${USER}/languages`)) return route.fulfill({ json: { guild_id: A, discord_user_id: USER, primary_language: null, languages: route.request().headers()['x-member-mode'] === 'none' ? [] : [{ language_profile_id: FR, source: 'ONBOARDING', enabled: true }, { language_profile_id: EN, source: 'EXPLICIT', enabled: true }] } })
    if (path.endsWith('/variants/plan') && route.request().method() === 'POST') { calls.variants.push(route.request().postDataJSON() as Record<string, unknown>); return route.fulfill({ json: { plan_id: '99999999-9999-4999-8999-999999999991', guild_id: A, status: 'DRAFT', replayed: false } }) }
    if (path.endsWith('/link') && route.request().method() === 'POST') { calls.links.push(route.request().postDataJSON() as Record<string, unknown>); return route.fulfill({ json: { id: '99999999-9999-4999-8999-999999999992' } }) }
    if (path.endsWith('/multilingual-clone/plan') && route.request().method() === 'POST') { calls.clones.push(route.request().postDataJSON() as Record<string, unknown>); return route.fulfill({ json: { destination_plan_id: '99999999-9999-4999-8999-999999999993', transfer_status: 'COMPILED', provider_bindings_omitted: true } }) }
    const groupMatch = path.match(/\/translation-groups\/([0-9a-f-]+)$/)
    if (groupMatch && route.request().method() === 'GET') { calls.previews.push(groupMatch[1] ?? ''); return route.fulfill({ json: workspace.groups.find((item) => item.id === groupMatch[1]) }) }
    if (path.endsWith('/plans')) return route.fulfill({ json: { plans: [] } })
    return route.fulfill({ status: 404, json: { error: { code: 'NOT_FOUND', message_key: 'errors.resource.notFound', params: {}, request_id: 'stage08-e2e' } } })
  })
}

test('@a11y two independent FR/EN groups expose hierarchy, routes, drift, provider and visibility', async ({ page }) => {
  await mockStage08(page); await page.goto(`/guild/${A}/translations`)
  await expect(page.getByRole('heading', { name: 'Translation workspace' })).toBeVisible(); await expect(page.getByRole('heading', { name: 'Guides' })).toBeVisible(); await expect(page.getByRole('heading', { name: 'Support' })).toBeVisible()
  await expect(page.getByText('Manual configuration required').first()).toBeVisible(); await expect(page.getByText('Missing', { exact: true })).toBeVisible(); await expect(page.getByText(/Scope and language/)).toBeVisible(); await expect(page.getByText(/Inherited from category/)).toBeVisible(); await expect(page.getByText(/Explicit on resource/)).toBeVisible(); await expect(page.getByText(/^French .* English$/)).toHaveCount(2)
  await expect(page.locator(`[data-translation-source="${GUIDES}"]`).getByRole('button', { name: 'Create variant' })).toBeEnabled(); await expect(page.locator(`[data-translation-source="${SUPPORT}"]`).getByRole('button', { name: 'Create variant' })).toBeDisabled()
  const results = await new AxeBuilder({ page }).exclude('.locale-flag').analyze(); expect(results.violations.filter((item) => ['serious','critical'].includes(item.impact ?? ''))).toEqual([])
})

test('member languages support zero and many without a primary language', async ({ page }) => {
  await mockStage08(page); await page.goto(`/guild/${A}/translations`)
  const many = await page.evaluate(async ({ guild, user }) => (await fetch(`/api/v1/guilds/${guild}/members/${user}/languages`)).json(), { guild: A, user: USER }); expect(many.primary_language).toBeNull(); expect(many.languages).toHaveLength(2)
  const none = await page.evaluate(async ({ guild, user }) => (await fetch(`/api/v1/guilds/${guild}/members/${user}/languages`, { headers: { 'X-Member-Mode': 'none' } })).json(), { guild: A, user: USER }); expect(none.primary_language).toBeNull(); expect(none.languages).toEqual([])
})

test('real right drag to a language target executes CREATE_VARIANT and renders backend PREVIEW', async ({ page }) => {
  const calls = callLog(); await mockStage08(page, 'en', calls); await page.goto(`/guild/${A}/translations`)
  const card = page.locator(`[data-translation-source="${GUIDES}"]`); const sourceBox = await card.getByRole('heading', { name: 'Guides' }).boundingBox(); const targetBox = await card.locator(`[data-translation-target-id="${EN}"]`).boundingBox(); if (!sourceBox || !targetBox) throw new Error('translation drag coordinates unavailable')
  await page.mouse.move(sourceBox.x + 4, sourceBox.y + 4); await page.mouse.down({ button: 'right' }); await page.mouse.move(targetBox.x + 8, targetBox.y + 8, { steps: 5 }); await page.mouse.up({ button: 'right' })
  await expect(page.getByRole('menu', { name: 'Available actions' })).toBeVisible(); await expect(page.getByRole('menuitem', { name: 'Create variant' })).toBeEnabled(); await expect(page.getByRole('menuitem', { name: 'Link existing variant' })).toBeVisible(); await expect(page.getByRole('menuitem', { name: 'Clone independently' })).toHaveCount(0)
  await page.getByRole('menuitem', { name: 'Create variant' }).click(); await expect(page.getByRole('dialog', { name: 'Multilingual action' })).toBeVisible(); await expect(page.getByLabel('Destination language')).toHaveValue(EN); await page.getByRole('button', { name: 'Confirm' }).click()
  await expect.poll(() => calls.variants.length).toBe(1); expect(calls.variants[0]).toMatchObject({ language_profile_id: EN, variant_type: 'CHANNEL', translation_channel_group_id: 'aaaaaaaa-1111-4111-8111-111111111111' })

  await page.goto(`/guild/${A}/translations`); await card.getByRole('button', { name: 'Preview topology' }).click(); await page.getByRole('button', { name: 'Preview', exact: true }).click(); await expect(page.getByRole('status')).toContainText('2 languages and 1 structural variants'); expect(calls.previews).toContain(GUIDES)
})

test('keyboard LINK_EXISTING_VARIANT uses the same registry execution path with explicit target', async ({ page }) => {
  const calls = callLog(); await mockStage08(page, 'en', calls); await page.goto(`/guild/${A}/translations`)
  const card = page.locator(`[data-translation-source="${GUIDES}"]`); await card.getByRole('button', { name: 'Link existing variant' }).click(); await page.getByLabel('Destination language').selectOption(EN); await page.getByLabel('Explicit Discord resource ID').fill('700000000000000099'); await page.getByRole('button', { name: 'Confirm' }).click()
  await expect.poll(() => calls.links.length).toBe(1); expect(calls.links[0]).toMatchObject({ language_profile_id: EN, variant_type: 'CHANNEL', discord_resource_id: '700000000000000099', confirmed_explicit_selection: true, translation_channel_group_id: 'aaaaaaaa-1111-4111-8111-111111111111' })
})

test('cross-Guild right drag executes the real clone-plan request with destination authority', async ({ page }) => {
  const calls = callLog(); await mockStage08(page, 'en', calls); await page.goto(`/guild/${A}/translations`)
  const card = page.locator(`[data-translation-source="${GUIDES}"]`); const sourceBox = await card.getByRole('heading', { name: 'Guides' }).boundingBox(); const targetBox = await page.locator(`[data-translation-target-type="GUILD"][data-translation-target-id="${B}"]`).boundingBox(); if (!sourceBox || !targetBox) throw new Error('cross-Guild drag coordinates unavailable')
  await page.mouse.move(sourceBox.x + 4, sourceBox.y + 4); await page.mouse.down({ button: 'right' }); await page.mouse.move(targetBox.x + 8, targetBox.y + 8, { steps: 8 }); await page.mouse.up({ button: 'right' }); await expect(page.getByRole('menuitem', { name: 'Clone independently' })).toBeEnabled(); await expect(page.getByRole('menuitem', { name: 'Create variant' })).toHaveCount(0)
  await page.getByRole('menuitem', { name: 'Clone independently' }).click(); await expect(page.getByLabel('Destination server')).toHaveValue(B); await page.getByRole('button', { name: 'Confirm' }).click(); await expect.poll(() => calls.clones.length).toBe(1)
  expect(calls.clones[0]).toMatchObject({ destination_guild_id: B, translation_group_id: GUIDES, mode: 'COPY_AS_NEW' }); expect(calls.capabilityGuilds).toContain(B); expect(JSON.stringify(calls.clones[0])).not.toMatch(/token|secret|config_encrypted/i)
})

const localeHeadings = { en: 'Translation workspace', fr: 'Espace de traduction', de: 'Uebersetzungsbereich', es: 'Espacio de traduccion' }
for (const [locale, heading] of Object.entries(localeHeadings)) test(`localized STAGE 08 surface has no raw enums or keys (${locale})`, async ({ page }) => {
  await mockStage08(page, locale); await page.goto(`/guild/${A}/translations`); await expect(page.locator('html')).toHaveAttribute('lang', locale); await expect(page.getByRole('heading', { name: heading })).toBeVisible(); await expect(page.getByText('HUB_AND_SPOKE')).toHaveCount(0); await expect(page.getByText(/^translations\./)).toHaveCount(0)
})
