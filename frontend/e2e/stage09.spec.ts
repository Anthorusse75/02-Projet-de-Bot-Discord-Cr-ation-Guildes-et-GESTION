import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

const A = '700000000000000001'; const B = '700000000000000002'; const USER = '700000000000000003'
const CHANNEL = '700000000000000010'
const CAMPAIGN_ID = '99999999-9999-4999-8999-999999999901'
const LOGICAL_GROUP_ID = '99999999-9999-4999-8999-999999999910'
const TRANSLATION_GROUP_ID = '99999999-9999-4999-8999-999999999920'
const LANGUAGE_FR = '99999999-9999-4999-8999-999999999930'
const LANGUAGE_DE = '99999999-9999-4999-8999-999999999931'

type Stage09State = {
  campaigns: Array<Record<string, unknown>>
  targets: Array<Record<string, unknown>>
  deliveries: Array<Record<string, unknown>>
}
function freshState(): Stage09State {
  return {
    campaigns: [{
      id: CAMPAIGN_ID, owner_discord_user_id: USER, logical_campaign_key: 'k', name: 'Autumn sale', source_language_code: 'en',
      message_model: { content: 'Hello everyone', embeds: [] }, allowed_mentions_policy: {}, publication_mode: 'IMMEDIATE',
      attachment_policy: 'PRESERVE_EXISTING', lifecycle_status: 'DRAFT', version: 1, created_at: '2026-08-30T00:00:00Z', updated_at: '2026-08-30T00:00:00Z',
    }],
    targets: [],
    deliveries: [{
      id: 'delivery-1', guild_id: A, campaign_id: CAMPAIGN_ID, occurrence_id: 'occurrence-1', target_id: 'target-1', language_profile_id: null,
      delivery_key: 'dk-1', discord_channel_id: CHANNEL, status: 'SENT', discord_message_id: '1', attempt_count: 1, last_error: null,
      created_at: '2026-08-30T00:00:00Z', updated_at: '2026-08-30T00:00:00Z',
    }],
  }
}

async function mockStage09(page: Page, locale = 'en', state: Stage09State = freshState()) {
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    const method = route.request().method()
    if (path === '/api/v1/ui/locales') return route.fulfill({ json: { catalog_version: 'did-ui-v2', locales: ['en','fr','de','es'].map((code) => ({ locale_code: code, display_name: code.toUpperCase(), flag_code: code, direction: 'ltr' })) } })
    if (path.startsWith('/api/v1/ui/locales/')) return route.fulfill({ status: 404, json: { error: { code: 'NOT_FOUND', message_key: 'errors.resource.notFound', params: {}, request_id: 'stage09-e2e' } } })
    if (path === '/api/v1/me') return route.fulfill({ json: { authenticated: true, user: { discord_user_id: USER, username: 'owner', global_name: 'Owner' }, active_guild_id: A, csrf_token: 'csrf', policy_version: 1 } })
    if (path === '/api/v1/me/preferences') return route.fulfill({ json: method === 'GET' ? { ui_locale_override_code: locale, timezone: null } : route.request().postDataJSON() })
    if (path === '/api/v1/guilds') return route.fulfill({ json: { guilds: [{ guild_id: A, name: 'Alpha', owner: true, permissions: '8', installation_status: 'ACTIVE' }, { guild_id: B, name: 'Beta', owner: true, permissions: '8', installation_status: 'ACTIVE' }] } })
    if (path.endsWith('/dashboard-capabilities')) { const guild = path.split('/')[4] ?? A; const can = { outcome: 'CAN', causes: [], remediations: [] }; const user = { 'structure.read': can, 'structure.write': can, 'plans.create': can }; return route.fulfill({ json: { guild_id: guild, source: 'AUTHORIZATION_AND_LOCAL_CACHE', discord_rest_calls: 0, user_capabilities: user, scoped_capabilities: { scope_kind: 'GUILD', scope_id: '*', capabilities: user }, bot_operations: { CREATE_CHANNEL: { ...can, operation: 'CREATE_CHANNEL', required_permissions: [] } }, coverage: 'FULL', completeness: 'FULL', freshness: 'FRESH' } }) }
    if (path.endsWith('/structure')) { const guild = path.split('/')[4] ?? A; return route.fulfill({ json: { guild_id: guild, source: 'LOCAL_CACHE', discord_rest_calls: 0, categories: [], root_channels: [{ guild_id: guild, id: CHANNEL, type: 0, name: 'general', position: 0, parent_id: null, resource_kind: 'CHANNEL', observability: 'VISIBLE', freshness: 'FRESH', data_assertion: 'OBSERVED' }] } }) }
    if (path.endsWith('/logical-groups') && method === 'GET') { const guild = path.split('/')[4] ?? A; return route.fulfill({ json: { guild_id: guild, resource_kind: 'DID_LOGICAL_RESOURCE', groups: [{ id: LOGICAL_GROUP_ID, guild_id: guild, name: 'VIP channels', slug: 'vip-channels', description: null }] } }) }
    if (path.endsWith('/translation-workspace')) {
      const guild = path.split('/')[4] ?? A
      const languageEn = { id: 'lang-en', guild_id: guild, code: 'en', display_name: 'English', emoji: null, enabled: true }
      const languageFr = { id: LANGUAGE_FR, guild_id: guild, code: 'fr', display_name: 'French', emoji: null, enabled: true }
      const languageDe = { id: LANGUAGE_DE, guild_id: guild, code: 'de', display_name: 'German', emoji: null, enabled: true }
      const group = { id: TRANSLATION_GROUP_ID, guild_id: guild, name: 'Announcements', root_kind: 'CHANNEL_SET', routing_mode: 'HUB_AND_SPOKE', visibility_scope_id: null, source_language_profile_id: 'lang-en', provider_binding_id: null, status: 'ACTIVE', version: 1, languages: [languageEn, languageFr, languageDe], category_variants: [], channel_groups: [], channel_variants: [], routes: [] }
      return route.fulfill({ json: { guild_id: guild, source: 'DURABLE_TOPOLOGY_AND_LOCAL_DISCORD_CACHE', discord_rest_calls: 0, cache_coverage: { mode: 'FULL', freshness: 'FRESH', roles_complete: true, channels_complete: true, members_complete: true, state_version: 1 }, groups: [group], providers: [], visibility_bindings: [], languages: [languageEn, languageFr, languageDe], resource_language_policies: [] } })
    }
    if (path === '/api/v1/campaigns' && method === 'GET') return route.fulfill({ json: { campaigns: state.campaigns } })
    if (path === '/api/v1/campaigns' && method === 'POST') {
      const body = route.request().postDataJSON() as Record<string, unknown>
      const created = { id: `created-${state.campaigns.length + 1}`, owner_discord_user_id: USER, logical_campaign_key: 'k2', name: body.name, source_language_code: body.source_language_code, message_model: body.message_model, allowed_mentions_policy: body.allowed_mentions_policy, publication_mode: body.publication_mode, attachment_policy: 'PRESERVE_EXISTING', lifecycle_status: 'DRAFT', version: 1, created_at: '2026-08-31T00:00:00Z', updated_at: '2026-08-31T00:00:00Z' }
      state.campaigns.push(created)
      return route.fulfill({ status: 201, json: { created: true, campaign: created } })
    }
    const patchMatch = path.match(/^\/api\/v1\/campaigns\/([^/]+)$/)
    if (patchMatch && method === 'PATCH') {
      const id = patchMatch[1]; const body = route.request().postDataJSON() as Record<string, unknown>
      state.campaigns = state.campaigns.map((item) => item.id === id ? { ...item, message_model: body.message_model ?? item.message_model, allowed_mentions_policy: body.allowed_mentions_policy ?? item.allowed_mentions_policy, version: Number(item.version) + 1 } : item)
      return route.fulfill({ json: state.campaigns.find((item) => item.id === id) })
    }
    if (path.endsWith('/targets') && method === 'GET') return route.fulfill({ json: { targets: state.targets } })
    if (path.endsWith('/targets') && method === 'POST') {
      const body = route.request().postDataJSON() as Record<string, unknown>
      const target = {
        id: `target-${state.targets.length + 1}`, guild_id: body.guild_id, campaign_id: path.split('/')[4], target_kind: body.target_kind,
        discord_channel_id: body.discord_channel_id ?? null, translation_group_id: body.translation_group_id ?? null,
        translation_publication_mode: body.translation_publication_mode ?? null, selected_language_profile_ids: body.selected_language_profile_ids ?? [],
        logical_group_id: body.logical_group_id ?? null,
      }
      state.targets.push(target)
      return route.fulfill({ status: 201, json: { target, bot_send_preflight_ok: true } })
    }
    if (path.endsWith('/schedule') && method === 'POST') {
      const body = route.request().postDataJSON() as Record<string, unknown>
      return route.fulfill({ status: 201, json: { id: 'schedule-1', campaign_id: path.split('/')[4], schedule_kind: body.schedule_kind, fire_at: body.fire_at ?? null, rrule: body.rrule ?? null, timezone: body.timezone ?? null, starts_at: body.starts_at ?? null, misfire_policy: 'SKIP_MISSED', dst_nonexistent_policy: 'SHIFT_FORWARD', dst_ambiguous_policy: 'EARLIEST', catch_up_bound: 1, next_fire_at: '2026-09-05T12:00:00Z', version: 1 } })
    }
    if (path.endsWith('/simulate') && method === 'POST') return route.fulfill({ json: { destinations: [{ guild_id: A, discord_channel_id: CHANNEL, language_profile_id: null, ready: true, blocked_reason: null, translation_state: 'SOURCE', delivery_executable: true }], total_destinations: 1, ready_destinations: 1, blocked_destinations: 0, estimated_delivery_count: 1, blockers: [] } })
    const lifecycleMatch = path.match(/^\/api\/v1\/campaigns\/([^/]+)\/(activate|pause|resume|cancel)$/)
    if (lifecycleMatch && method === 'POST') {
      const [, id, action] = lifecycleMatch
      const next = action === 'activate' ? 'ACTIVE_RUNNING' : action === 'pause' ? 'PAUSED' : action === 'resume' ? 'ACTIVE_RUNNING' : 'CANCELLED'
      state.campaigns = state.campaigns.map((item) => item.id === id ? { ...item, lifecycle_status: next } : item)
      const updated = state.campaigns.find((item) => item.id === id)
      return route.fulfill({ json: action === 'activate' ? { campaign: updated, durable_work: { occurrence_created: true, deliveries_created: 1, deliveries_routed: 1, is_fully_healthy: true } } : updated })
    }
    if (path.endsWith('/deliveries') && method === 'GET') return route.fulfill({ json: { deliveries: state.deliveries } })
    const variantMatch = path.match(/\/variants\/([^/]+)$/)
    if (variantMatch && method === 'GET') return route.fulfill({ json: { campaign_id: path.split('/')[4], target_language_code: decodeURIComponent(variantMatch[1] ?? ''), outcome: 'MISSING', current_source_fingerprint: 'fp', approved_variant: null } })
    if (path.includes('/variants/') && path.endsWith('/approve') && method === 'POST') {
      const body = route.request().postDataJSON() as Record<string, unknown>
      return route.fulfill({ status: 201, json: { id: 'variant-1', campaign_id: path.split('/')[4], target_language_code: 'fr', source_fingerprint: 'fp', localized_message_model: body.localized_message_model, approved_by_discord_user_id: USER, approved_at: '2026-08-31T00:00:00Z' } })
    }
    return route.fulfill({ status: 404, json: { error: { code: 'NOT_FOUND', message_key: 'errors.resource.notFound', params: {}, request_id: 'stage09-e2e' } } })
  })
}

test('@a11y full campaign lifecycle: create, target, preview, activate, deliveries, variant approval', async ({ page }) => {
  const state = freshState()
  await mockStage09(page, 'en', state)
  await page.goto(`/guild/${A}/campaigns`)
  await expect(page.getByRole('heading', { name: 'Message & campaign center' })).toBeVisible()

  await page.getByLabel('Campaign name').fill('Winter drop')
  await page.getByLabel('Message content').fill('Big winter sale starts now')
  await page.getByRole('button', { name: 'Create campaign' }).click()
  await expect(page.getByRole('heading', { name: 'Campaign detail' })).toBeVisible()

  await page.getByLabel('Destination server').selectOption(A)
  await expect(page.getByLabel('Destination channel').locator('option', { hasText: 'general' })).toHaveCount(1)
  await page.getByLabel('Destination channel').selectOption(CHANNEL)
  await page.getByRole('button', { name: 'Add target' }).click()
  await expect(page.getByText('Target added.')).toBeVisible()

  await page.getByRole('button', { name: 'Run preview' }).click()
  await expect(page.getByText('1 of 1 destinations ready (1 estimated deliveries)')).toBeVisible()

  await page.getByRole('button', { name: 'Activate' }).click()
  await expect(page.locator('.campaign-detail').getByText('Active')).toBeVisible()

  await expect(page.getByText('Sent')).toBeVisible()

  await page.getByLabel('Target language code').fill('fr')
  await page.getByRole('button', { name: 'Check variant' }).click()
  await expect(page.getByText('Missing')).toBeVisible()
  await page.getByLabel('Localized content').fill('Grande vente d’hiver')
  await page.getByRole('button', { name: 'Approve variant' }).click()
  await expect(page.getByText('Variant approved.')).toBeVisible()

  const results = await new AxeBuilder({ page }).exclude('.locale-flag').analyze()
  expect(results.violations.filter((item) => ['serious','critical'].includes(item.impact ?? ''))).toEqual([])
})

test('pause, resume and cancel lifecycle controls call the real endpoints and reflect status', async ({ page }) => {
  const state = freshState()
  state.campaigns[0].lifecycle_status = 'ACTIVE_RUNNING'
  await mockStage09(page, 'en', state)
  await page.goto(`/guild/${A}/campaigns`)
  await page.getByRole('button', { name: /Autumn sale/ }).click()
  await expect(page.getByRole('heading', { name: 'Campaign detail' })).toBeVisible()

  await page.getByRole('button', { name: 'Pause' }).click()
  await expect(page.locator('.campaign-detail').getByText('Paused')).toBeVisible()
  await page.getByRole('button', { name: 'Resume' }).click()
  await expect(page.locator('.campaign-detail').getByText('Active')).toBeVisible()
  await page.locator('.campaign-lifecycle').getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(page.locator('.campaign-detail').getByText('Cancelled')).toBeVisible()
  await expect(page.locator('.campaign-lifecycle').getByRole('button', { name: 'Cancel', exact: true })).toBeDisabled()
})

test('@a11y REQ-MSG-007: CHANNEL, LOGICAL_GROUP and every TRANSLATION_GROUP publication mode can be targeted', async ({ page }) => {
  const state = freshState()
  await mockStage09(page, 'en', state)
  await page.goto(`/guild/${A}/campaigns`)
  await page.getByRole('button', { name: /Autumn sale/ }).click()
  await expect(page.getByRole('heading', { name: 'Campaign detail' })).toBeVisible()
  await page.getByLabel('Destination server').selectOption(A)

  // Select IDs are stable and unambiguous, unlike accessible names here: a
  // native <select> nested inside its own <label> computes its accessible
  // name from the label text PLUS its currently selected option's text
  // (browser behavior, not a bug in this component) -- e.g. once "Target
  // kind" has "Logical group" selected, its own computed name becomes
  // "Target kindLogical group", which collides with the actual "Logical
  // group" selector's name under getByLabel's substring matching. ID-based
  // locators sidestep this entirely.
  const logicalGroupSelect = page.locator('[id="select-campaigns.targets.logicalGroup"]')
  const translationGroupSelect = page.locator('[id="select-campaigns.targets.translationGroup"]')
  const translationModeSelect = page.locator('[id="select-campaigns.targets.translationMode"]')

  // --- LOGICAL_GROUP: real Stage04 logical groups, never a fake dropdown.
  await page.getByLabel('Target kind').selectOption('LOGICAL_GROUP')
  await expect(logicalGroupSelect.locator('option', { hasText: 'VIP channels' })).toHaveCount(1)
  await logicalGroupSelect.selectOption(LOGICAL_GROUP_ID)
  await page.getByRole('button', { name: 'Add target' }).click()
  await expect(page.getByText('Target added.')).toBeVisible()

  // --- TRANSLATION_GROUP, each of the 4 publication modes -- real Stage08
  // Translation Groups and Language Profiles, never hardcoded ids.
  await page.getByLabel('Target kind').selectOption('TRANSLATION_GROUP')
  await expect(translationGroupSelect.locator('option', { hasText: 'Announcements' })).toHaveCount(1)
  await translationGroupSelect.selectOption(TRANSLATION_GROUP_ID)

  for (const mode of ['SOURCE_ONLY', 'EXISTING_PROVIDER', 'DID_TRANSLATED_FANOUT'] as const) {
    // A successful add resets the target-scoping selections (same as for
    // CHANNEL/LOGICAL_GROUP) so the form is ready for the next distinct
    // destination -- re-select the Translation Group each time to add
    // another target against it under a different publication mode.
    await translationGroupSelect.selectOption(TRANSLATION_GROUP_ID)
    await translationModeSelect.selectOption(mode)
    await page.getByRole('button', { name: 'Add target' }).click()
    await expect(page.getByText('Target added.')).toBeVisible()
  }

  await translationGroupSelect.selectOption(TRANSLATION_GROUP_ID)
  await translationModeSelect.selectOption('SELECTED_LANGUAGES')
  await expect(page.getByRole('button', { name: 'Add target' })).toBeDisabled()
  await page.getByRole('checkbox', { name: 'French' }).check()
  await page.getByRole('checkbox', { name: 'German' }).check()
  await expect(page.getByRole('button', { name: 'Add target' })).toBeEnabled()
  await page.getByRole('button', { name: 'Add target' }).click()
  await expect(page.getByText('Target added.')).toBeVisible()

  await expect(page.locator('.campaign-targets li')).toHaveCount(5)
  expect(state.targets.map((target) => target.target_kind)).toEqual([
    'LOGICAL_GROUP', 'TRANSLATION_GROUP', 'TRANSLATION_GROUP', 'TRANSLATION_GROUP', 'TRANSLATION_GROUP',
  ])
  const selectedLanguagesTarget = state.targets[4] as Record<string, unknown>
  expect(selectedLanguagesTarget.translation_publication_mode).toBe('SELECTED_LANGUAGES')
  expect(selectedLanguagesTarget.selected_language_profile_ids).toEqual([LANGUAGE_FR, LANGUAGE_DE])

  const results = await new AxeBuilder({ page }).exclude('.locale-flag').analyze()
  expect(results.violations.filter((item) => ['serious', 'critical'].includes(item.impact ?? ''))).toEqual([])
})

const localeHeadings = { en: 'Message & campaign center', fr: 'Centre de messages et campagnes', de: 'Nachrichten- und Kampagnenzentrale', es: 'Centro de mensajes y campañas' }
for (const [locale, heading] of Object.entries(localeHeadings)) test(`localized STAGE 09 surface has no raw enums or keys (${locale})`, async ({ page }) => {
  const state = freshState(); state.campaigns[0].lifecycle_status = 'PAUSED'
  await mockStage09(page, locale, state)
  await page.goto(`/guild/${A}/campaigns`)
  await expect(page.locator('html')).toHaveAttribute('lang', locale)
  await expect(page.getByRole('heading', { name: heading })).toBeVisible()
  await page.getByRole('button', { name: /Autumn sale/ }).click()
  await expect(page.locator('.campaign-detail')).toBeVisible()
  await expect(page.getByText('PAUSED', { exact: true })).toHaveCount(0)
  await expect(page.getByText(/^campaigns\./)).toHaveCount(0)
  await expect(page.getByText(/^errors\.campaigns\./)).toHaveCount(0)
})
