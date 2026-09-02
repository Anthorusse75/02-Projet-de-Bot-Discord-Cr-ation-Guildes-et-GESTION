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
  templateVariables: Array<Record<string, unknown>>
  glossaryEntries: Array<Record<string, unknown>>
  triggers: Array<Record<string, unknown>>
  triggerSources: Array<Record<string, unknown>>
}
function freshState(): Stage09State {
  return {
    campaigns: [{
      id: CAMPAIGN_ID, owner_discord_user_id: USER, logical_campaign_key: 'k', name: 'Autumn sale', source_language_code: 'en',
      message_model: { content: 'Hello everyone', embeds: [], action_rows: [] }, allowed_mentions_policy: {}, publication_mode: 'IMMEDIATE',
      attachment_policy: 'PRESERVE_EXISTING', lifecycle_status: 'DRAFT', version: 1, created_at: '2026-08-30T00:00:00Z', updated_at: '2026-08-30T00:00:00Z',
    }],
    targets: [],
    deliveries: [{
      id: 'delivery-1', guild_id: A, campaign_id: CAMPAIGN_ID, occurrence_id: 'occurrence-1', target_id: 'target-1', language_profile_id: null,
      delivery_key: 'dk-1', discord_channel_id: CHANNEL, status: 'SENT', discord_message_id: '1', attempt_count: 1, last_error: null,
      created_at: '2026-08-30T00:00:00Z', updated_at: '2026-08-30T00:00:00Z',
    }],
    templateVariables: [],
    glossaryEntries: [],
    triggers: [],
    triggerSources: [],
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
    if (path.endsWith('/simulate') && method === 'POST') {
      const campaignId = path.split('/')[4]
      const campaign = state.campaigns.find((item) => item.id === campaignId)
      const content = String((campaign?.message_model as { content?: string } | undefined)?.content ?? '')
      const declaredNames = new Set(state.templateVariables.map((item) => item.name))
      const referencedNames = [...content.matchAll(/\{\{([^}]+)\}\}/g)].map((match) => match[1])
      const undeclared = [...new Set(referencedNames.filter((name) => !declaredNames.has(name)))].sort()
      const applicableGlossary = state.glossaryEntries.filter((entry) =>
        entry.scope_kind === 'GLOBAL_USER' || (entry.scope_kind === 'CAMPAIGN' && entry.campaign_id === campaignId))
      const matchedGlossaryTerms = applicableGlossary
        .filter((entry) => content.includes(String(entry.source_term)))
        .map((entry) => String(entry.source_term))
      return route.fulfill({ json: { destinations: [{ guild_id: A, discord_channel_id: CHANNEL, language_profile_id: null, ready: true, blocked_reason: null, translation_state: 'SOURCE', delivery_executable: true }], total_destinations: 1, ready_destinations: 1, blocked_destinations: 0, estimated_delivery_count: 1, blockers: {}, message_content_warnings: [], undeclared_template_variable_names: undeclared, matched_glossary_terms: matchedGlossaryTerms } })
    }
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
    const resolveMatch = path.match(/\/deliveries\/([^/]+)\/intervention\/resolve$/)
    if (resolveMatch && method === 'POST') {
      const body = route.request().postDataJSON() as Record<string, unknown>
      const nextStatus = body.resolution === 'SENT' ? 'SENT' : 'FAILED'
      state.deliveries = state.deliveries.map((item) => item.id === resolveMatch[1]
        ? { ...item, status: nextStatus, discord_message_id: body.discord_message_id ?? null, last_error: nextStatus === 'FAILED' ? 'confirmed not sent' : null }
        : item)
      return route.fulfill({ json: { delivery: state.deliveries.find((item) => item.id === resolveMatch[1]) } })
    }
    const requeueMatch = path.match(/\/deliveries\/([^/]+)\/requeue$/)
    if (requeueMatch && method === 'POST') {
      state.deliveries = state.deliveries.map((item) => item.id === requeueMatch[1]
        ? { ...item, status: 'PENDING', discord_message_id: null, last_error: null }
        : item)
      return route.fulfill({ json: { delivery: state.deliveries.find((item) => item.id === requeueMatch[1]) } })
    }
    const editMatch = path.match(/\/deliveries\/([^/]+)\/edit$/)
    if (editMatch && method === 'POST') {
      return route.fulfill({ json: { delivery: state.deliveries.find((item) => item.id === editMatch[1]) } })
    }
    const deleteMatch = path.match(/\/deliveries\/([^/]+)\/delete$/)
    if (deleteMatch && method === 'POST') {
      return route.fulfill({ json: { delivery: state.deliveries.find((item) => item.id === deleteMatch[1]) } })
    }
    if (path.endsWith('/template-variables') && method === 'GET') {
      return route.fulfill({ json: { template_variables: state.templateVariables } })
    }
    if (path.endsWith('/template-variables') && method === 'POST') {
      const body = route.request().postDataJSON() as Record<string, unknown>
      const created = {
        id: `tv-${state.templateVariables.length + 1}`, campaign_id: path.split('/')[4], name: body.name,
        variable_type: body.variable_type, value: body.value ?? null, values_by_language: body.values_by_language ?? null,
      }
      state.templateVariables.push(created)
      return route.fulfill({ status: 201, json: created })
    }
    const templateVariableMatch = path.match(/\/template-variables\/([^/]+)$/)
    if (templateVariableMatch && method === 'PATCH') {
      const body = route.request().postDataJSON() as Record<string, unknown>
      state.templateVariables = state.templateVariables.map((item) => item.id === templateVariableMatch[1]
        ? { ...item, variable_type: body.variable_type, value: body.value ?? null, values_by_language: body.values_by_language ?? null }
        : item)
      return route.fulfill({ json: state.templateVariables.find((item) => item.id === templateVariableMatch[1]) })
    }
    if (templateVariableMatch && method === 'DELETE') {
      state.templateVariables = state.templateVariables.filter((item) => item.id !== templateVariableMatch[1])
      return route.fulfill({ status: 204, body: '' })
    }
    const campaignGlossaryMatch = path.match(/^\/api\/v1\/campaigns\/([^/]+)\/glossary$/)
    if (campaignGlossaryMatch && method === 'GET') {
      return route.fulfill({ json: { glossary_entries: state.glossaryEntries.filter((entry) => entry.campaign_id === campaignGlossaryMatch[1]) } })
    }
    const guildGlossaryMatch = path.match(/^\/api\/v1\/guilds\/([^/]+)\/glossary$/)
    if (guildGlossaryMatch && method === 'GET') {
      return route.fulfill({ json: { glossary_entries: state.glossaryEntries.filter((entry) => entry.guild_id === guildGlossaryMatch[1]) } })
    }
    if (path === '/api/v1/glossary' && method === 'GET') {
      return route.fulfill({ json: { glossary_entries: state.glossaryEntries.filter((entry) => entry.scope_kind === 'GLOBAL_USER') } })
    }
    if (path === '/api/v1/glossary' && method === 'POST') {
      const body = route.request().postDataJSON() as Record<string, unknown>
      const created = {
        id: `glossary-${state.glossaryEntries.length + 1}`, scope_kind: body.scope_kind, source_term: body.source_term, behavior: body.behavior,
        campaign_id: body.campaign_id ?? null, guild_id: body.guild_id ?? null, target_language_code: body.target_language_code ?? null,
        forced_translation: body.forced_translation ?? null, match_mode: body.match_mode,
      }
      state.glossaryEntries.push(created)
      return route.fulfill({ status: 201, json: created })
    }
    const glossaryDeleteMatch = path.match(/^\/api\/v1\/glossary\/([^/]+)$/)
    if (glossaryDeleteMatch && method === 'DELETE') {
      state.glossaryEntries = state.glossaryEntries.filter((entry) => entry.id !== glossaryDeleteMatch[1])
      return route.fulfill({ status: 204, body: '' })
    }
    const triggersMatch = path.match(/^\/api\/v1\/campaigns\/([^/]+)\/triggers$/)
    if (triggersMatch && method === 'GET') {
      return route.fulfill({ json: { triggers: state.triggers.filter((item) => item.campaign_id === triggersMatch[1]) } })
    }
    if (triggersMatch && method === 'POST') {
      const body = route.request().postDataJSON() as Record<string, unknown>
      // REQ-MSG-020, Option B: Stage09 has no content-capture capability at
      // all right now, so a trigger declaring requires_message_content is
      // always rejected -- mirrors did.campaigns.message_content_policy's
      // real, permanent block so the UI's warning is exercised honestly.
      if (body.requires_message_content === true) {
        return route.fulfill({ status: 422, json: { error: { code: 'CAMPAIGN_TRIGGER_MESSAGE_CONTENT_UNAVAILABLE', message_key: 'errors.campaigns.triggerMessageContentUnavailable', params: {}, request_id: 'stage09-e2e' } } })
      }
      const created = {
        id: `trigger-${state.triggers.length + 1}`, campaign_id: triggersMatch[1], event_type: body.event_type,
        condition_ast: body.condition_ast, max_causation_depth: body.max_causation_depth, requires_message_content: false, version: 1,
      }
      state.triggers.push(created)
      return route.fulfill({ status: 201, json: created })
    }
    const triggerSourcesMatch = path.match(/^\/api\/v1\/campaigns\/([^/]+)\/triggers\/([^/]+)\/sources$/)
    if (triggerSourcesMatch && method === 'GET') {
      const guildId = new URL(route.request().url()).searchParams.get('guild_id')
      return route.fulfill({ json: { trigger_sources: state.triggerSources.filter((item) => item.trigger_id === triggerSourcesMatch[2] && item.guild_id === guildId) } })
    }
    if (triggerSourcesMatch && method === 'POST') {
      const body = route.request().postDataJSON() as Record<string, unknown>
      const created = {
        id: `trigger-source-${state.triggerSources.length + 1}`, guild_id: body.guild_id, trigger_id: triggerSourcesMatch[2],
        source_scope_kind: body.source_scope_kind, discord_resource_id: body.discord_resource_id ?? null,
      }
      state.triggerSources.push(created)
      return route.fulfill({ status: 201, json: created })
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

test('@a11y REQ-MSG mission section 9: an embed and a button are authored and submitted with the campaign, never submitting the form early', async ({ page }) => {
  const state = freshState()
  await mockStage09(page, 'en', state)
  await page.goto(`/guild/${A}/campaigns`)
  await expect(page.getByRole('heading', { name: 'Message & campaign center' })).toBeVisible()

  await page.getByLabel('Campaign name').fill('Product launch')
  await page.getByLabel('Message content').fill('Big announcement')

  // Every "Add..." click below happens inside the create <form> -- proves
  // none of them are wired as a default type="submit" button that would
  // prematurely submit the campaign before authoring is finished.
  await page.getByRole('button', { name: 'Add embed' }).click()
  await page.getByLabel('Embed title').fill('Launch')
  await page.getByLabel('Embed description').fill('Big news')
  await page.getByLabel('Embed URL').fill('https://example.com/launch')
  await page.getByRole('button', { name: 'Add field' }).click()
  await page.getByLabel('Field name').fill('Starts')
  await page.getByLabel('Field value').fill('Today')

  await page.getByRole('button', { name: 'Add button row' }).click()
  await page.getByRole('button', { name: 'Add button', exact: true }).click()
  await page.getByLabel('Button label').fill('Confirm')
  await page.getByLabel('Button custom ID').fill('confirm-launch')

  await expect(page.getByRole('heading', { name: 'Campaign detail' })).toHaveCount(0)

  await page.getByRole('button', { name: 'Create campaign' }).click()
  await expect(page.getByRole('heading', { name: 'Campaign detail' })).toBeVisible()
  expect(state.campaigns).toHaveLength(2)
  const created = state.campaigns[1] as { message_model: { embeds: Array<Record<string, unknown>>; action_rows: Array<{ buttons: Array<Record<string, unknown>> }> } }
  expect(created.message_model.embeds[0]).toMatchObject({ title: 'Launch', description: 'Big news', url: 'https://example.com/launch' })
  expect(created.message_model.embeds[0]?.fields).toMatchObject([{ name: 'Starts', value: 'Today' }])
  expect(created.message_model.action_rows[0]?.buttons[0]).toMatchObject({ label: 'Confirm', style: 'PRIMARY', custom_id: 'confirm-launch' })

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

test('REQ-MSG-029: an intervention-required delivery is resolved as sent, a failed one is requeued', async ({ page }) => {
  const state = freshState()
  state.deliveries.push(
    { id: 'delivery-2', guild_id: A, campaign_id: CAMPAIGN_ID, occurrence_id: 'occurrence-2', target_id: 'target-1', language_profile_id: null, delivery_key: 'dk-2', discord_channel_id: CHANNEL, status: 'INTERVENTION_REQUIRED', discord_message_id: null, attempt_count: 4, last_error: 'ambiguous send outcome', created_at: '2026-08-30T00:00:00Z', updated_at: '2026-08-30T00:00:00Z' },
    { id: 'delivery-3', guild_id: A, campaign_id: CAMPAIGN_ID, occurrence_id: 'occurrence-3', target_id: 'target-1', language_profile_id: null, delivery_key: 'dk-3', discord_channel_id: CHANNEL, status: 'FAILED', discord_message_id: null, attempt_count: 1, last_error: 'discord rejected the request', created_at: '2026-08-30T00:00:00Z', updated_at: '2026-08-30T00:00:00Z' },
  )
  await mockStage09(page, 'en', state)
  await page.goto(`/guild/${A}/campaigns`)
  await page.getByRole('button', { name: /Autumn sale/ }).click()
  await expect(page.locator('.campaign-detail')).toBeVisible()
  const deliveries = page.locator('.campaign-deliveries')
  await expect(deliveries.getByText('Needs intervention')).toBeVisible()

  await deliveries.getByRole('button', { name: 'Resolve' }).click()
  await deliveries.getByLabel('Discord message ID').fill('123456789012345678')
  await deliveries.getByRole('button', { name: 'Confirm sent' }).click()
  await expect(page.getByText('Delivery resolved.')).toBeVisible()
  await expect(deliveries.getByText('Needs intervention')).toHaveCount(0)

  await deliveries.getByRole('button', { name: 'Requeue' }).click()
  await expect(page.getByText('Delivery requeued for a fresh attempt.')).toBeVisible()
  await expect(deliveries.getByText('Failed')).toHaveCount(0)

  const results = await new AxeBuilder({ page }).exclude('.locale-flag').analyze()
  expect(results.violations.filter((item) => ['serious', 'critical'].includes(item.impact ?? ''))).toEqual([])
})

test('REQ-MSG owned edit/delete: a sent delivery can be edited and deleted through the real product chain', async ({ page }) => {
  const state = freshState()
  await mockStage09(page, 'en', state)
  await page.goto(`/guild/${A}/campaigns`)
  await page.getByRole('button', { name: /Autumn sale/ }).click()
  await expect(page.locator('.campaign-detail')).toBeVisible()
  const deliveries = page.locator('.campaign-deliveries')
  await expect(deliveries.getByText('Sent', { exact: true })).toBeVisible()

  await deliveries.getByRole('button', { name: 'Edit' }).click()
  await deliveries.getByLabel('New message content').fill('Updated announcement text')
  await deliveries.getByRole('button', { name: 'Save edit' }).click()
  await expect(page.getByText('Edit queued for delivery.')).toBeVisible()

  await deliveries.getByRole('button', { name: 'Delete' }).click()
  await expect(page.getByText('Delete queued for delivery.')).toBeVisible()

  const results = await new AxeBuilder({ page }).exclude('.locale-flag').analyze()
  expect(results.violations.filter((item) => ['serious', 'critical'].includes(item.impact ?? ''))).toEqual([])
})

test('@a11y REQ-MSG-018 mission section 10: a typed template variable is authored, edited and deleted, and simulation surfaces undeclared ones', async ({ page }) => {
  const state = freshState()
  state.campaigns[0].message_model = { content: 'Hello {{name}}, {{unbound}} is waiting!', embeds: [], action_rows: [] }
  await mockStage09(page, 'en', state)
  await page.goto(`/guild/${A}/campaigns`)
  await page.getByRole('button', { name: /Autumn sale/ }).click()
  await expect(page.locator('.campaign-detail')).toBeVisible()
  const templateVariables = page.locator('.campaign-template-variables')

  await templateVariables.locator('#tv-create-name').fill('name')
  await templateVariables.locator('#tv-create-type').selectOption('TRANSLATABLE_TEXT')
  await templateVariables.locator('#tv-create-value').fill('Alex')
  await templateVariables.getByRole('button', { name: 'Add variable' }).click()
  await expect(page.getByText('Template variable created.')).toBeVisible()
  await expect(templateVariables.getByText('{{name}}')).toBeVisible()

  await templateVariables.getByRole('button', { name: 'Edit' }).click()
  await templateVariables.locator('[id^="tv-edit-"][id$="-value"]').fill('Jordan')
  await templateVariables.getByRole('button', { name: 'Confirm' }).click()
  await expect(page.getByText('Template variable updated.')).toBeVisible()

  // The simulation panel surfaces {{unbound}} (never declared) but not
  // {{name}} (declared, now with a real value).
  await page.getByRole('button', { name: 'Run preview' }).click()
  const simulationResult = page.locator('.simulation-result')
  await expect(simulationResult.getByText('Undeclared template variables')).toBeVisible()
  await expect(simulationResult.getByText('{{unbound}}')).toBeVisible()
  await expect(simulationResult.getByText('{{name}}', { exact: true })).toHaveCount(0)

  await templateVariables.getByRole('button', { name: 'Delete' }).click()
  await expect(page.getByText('Template variable deleted.')).toBeVisible()
  await expect(templateVariables.getByText('No template variable has been declared yet.')).toBeVisible()

  const results = await new AxeBuilder({ page }).exclude('.locale-flag').analyze()
  expect(results.violations.filter((item) => ['serious', 'critical'].includes(item.impact ?? ''))).toEqual([])
})

test('@a11y REQ-MSG-014 mission section 11: glossary terms are authored across all three scopes, matched terms surface in simulation, and a term can be deleted', async ({ page }) => {
  const state = freshState()
  state.campaigns[0].message_model = { content: 'Our Widget is on sale!', embeds: [], action_rows: [] }
  await mockStage09(page, 'en', state)
  await page.goto(`/guild/${A}/campaigns`)
  await page.getByRole('button', { name: /Autumn sale/ }).click()
  await expect(page.locator('.campaign-detail')).toBeVisible()
  const glossary = page.locator('.campaign-glossary')

  // CAMPAIGN scope (default): DO_NOT_TRANSLATE, no Guild id required.
  await glossary.locator('#glossary-create-term').fill('Widget')
  await glossary.getByRole('button', { name: 'Add term' }).click()
  await expect(page.getByText('Glossary term created.')).toBeVisible()
  await expect(glossary.getByText('Widget', { exact: true })).toBeVisible()

  // GLOBAL_USER scope, FORCED_TRANSLATION requires forced-translation text.
  await glossary.locator('#glossary-scope').selectOption('GLOBAL_USER')
  await glossary.locator('#glossary-create-term').fill('Brand')
  await glossary.locator('#glossary-create-behavior').selectOption('FORCED_TRANSLATION')
  await glossary.locator('#glossary-create-forced').fill('Marque')
  await glossary.getByRole('button', { name: 'Add term' }).click()
  await expect(page.getByText('Glossary term created.')).toBeVisible()
  await expect(glossary.getByText('Brand', { exact: true })).toBeVisible()

  // GUILD scope requires an explicit destination Guild id -- the list stays
  // empty until one is entered (there is no single "current Guild").
  await glossary.locator('#glossary-scope').selectOption('GUILD')
  await expect(glossary.getByText('Load')).toBeVisible()
  await glossary.locator('#glossary-guild-id').fill(A)
  await glossary.locator('#glossary-create-term').fill('ServerName')
  await glossary.getByRole('button', { name: 'Add term' }).click()
  await expect(page.getByText('Glossary term created.')).toBeVisible()
  await expect(glossary.getByText('ServerName', { exact: true })).toBeVisible()

  // The CAMPAIGN-scope "Widget" term literally appears in the campaign's
  // own message content, so preview surfaces it as a matched glossary term.
  await page.getByRole('button', { name: 'Run preview' }).click()
  const simulationResult = page.locator('.simulation-result')
  await expect(simulationResult.getByText('Matched glossary terms')).toBeVisible()
  await expect(simulationResult.getByText('Widget', { exact: true })).toBeVisible()

  await glossary.locator('#glossary-scope').selectOption('CAMPAIGN')
  await glossary.getByRole('button', { name: 'Delete' }).click()
  await expect(page.getByText('Glossary term deleted.')).toBeVisible()
  await expect(glossary.getByText('No glossary term has been declared yet.')).toBeVisible()

  const results = await new AxeBuilder({ page }).exclude('.locale-flag').analyze()
  expect(results.violations.filter((item) => ['serious', 'critical'].includes(item.impact ?? ''))).toEqual([])
})

test('@a11y REQ-MSG-027/030 mission section 12: an event trigger is authored with a structured condition, a source is bound, and the MESSAGE_CONTENT blocker is enforced end to end', async ({ page }) => {
  const state = freshState()
  state.campaigns[0].publication_mode = 'EVENT_TRIGGERED'
  await mockStage09(page, 'en', state)
  await page.goto(`/guild/${A}/campaigns`)
  await page.getByRole('button', { name: /Autumn sale/ }).click()
  await expect(page.locator('.campaign-detail')).toBeVisible()
  const triggers = page.locator('.campaign-triggers')
  await expect(triggers).toBeVisible()

  await triggers.locator('#trigger-create-event-type').fill('MESSAGE_CREATE')
  await triggers.locator('#trigger-create-condition-kind').selectOption('COMPARISON')
  await triggers.locator('#trigger-comparison-path').fill('author.bot')
  await triggers.locator('#trigger-comparison-value-type').selectOption('BOOLEAN')
  await triggers.locator('#trigger-comparison-value').fill('false')
  await triggers.locator('#trigger-create-depth').fill('4')
  await triggers.getByRole('button', { name: 'Add trigger' }).click()
  await expect(page.getByText('Event trigger created.')).toBeVisible()
  await expect(triggers.getByText('MESSAGE_CREATE')).toBeVisible()
  await expect(triggers.getByText('Max depth 4')).toBeVisible()

  // MESSAGE_CONTENT blocker semantics (REQ-MSG-020, Option B): declaring
  // the dependency is always rejected right now -- proven end to end
  // against the real error code/message, not merely a static UI warning.
  await triggers.locator('#trigger-create-event-type').fill('MESSAGE_UPDATE')
  await triggers.getByRole('checkbox', { name: 'Requires raw message content' }).check()
  await expect(triggers.getByText('This capability is not currently available')).toBeVisible()
  await triggers.getByRole('button', { name: 'Add trigger' }).click()
  await expect(page.getByText('This trigger requires message content, which is not currently supported.')).toBeVisible()
  await expect(triggers.getByText('MESSAGE_UPDATE')).toHaveCount(0)

  await triggers.getByRole('button', { name: 'Manage sources' }).click()
  const sourcesPanel = triggers.locator('.trigger-sources')
  await expect(sourcesPanel).toBeVisible()
  await sourcesPanel.locator('#trigger-source-guild-id').fill(A)
  await sourcesPanel.locator('#trigger-source-scope').selectOption('CHANNEL')
  await sourcesPanel.locator('#trigger-source-resource-id').fill(CHANNEL)
  await sourcesPanel.getByRole('button', { name: 'Add source' }).click()
  await expect(page.getByText('Trigger source added.')).toBeVisible()
  await expect(sourcesPanel.locator('.trigger-source-row').getByText('Channel', { exact: true })).toBeVisible()
  await expect(sourcesPanel.getByText(CHANNEL)).toBeVisible()

  const results = await new AxeBuilder({ page }).exclude('.locale-flag').analyze()
  expect(results.violations.filter((item) => ['serious', 'critical'].includes(item.impact ?? ''))).toEqual([])
})

const localeHeadings = { en: 'Message & campaign center', fr: 'Centre de messages et campagnes', de: 'Nachrichten- und Kampagnenzentrale', es: 'Centro de mensajes y campañas' }
for (const [locale, heading] of Object.entries(localeHeadings)) test(`localized STAGE 09 surface has no raw enums or keys (${locale})`, async ({ page }) => {
  const state = freshState(); state.campaigns[0].lifecycle_status = 'PAUSED'
  state.deliveries.push(
    { id: 'delivery-2', guild_id: A, campaign_id: CAMPAIGN_ID, occurrence_id: 'occurrence-2', target_id: 'target-1', language_profile_id: null, delivery_key: 'dk-2', discord_channel_id: CHANNEL, status: 'INTERVENTION_REQUIRED', discord_message_id: null, attempt_count: 4, last_error: 'ambiguous send outcome', created_at: '2026-08-30T00:00:00Z', updated_at: '2026-08-30T00:00:00Z' },
    { id: 'delivery-3', guild_id: A, campaign_id: CAMPAIGN_ID, occurrence_id: 'occurrence-3', target_id: 'target-1', language_profile_id: null, delivery_key: 'dk-3', discord_channel_id: CHANNEL, status: 'FAILED', discord_message_id: null, attempt_count: 1, last_error: 'discord rejected the request', created_at: '2026-08-30T00:00:00Z', updated_at: '2026-08-30T00:00:00Z' },
  )
  state.templateVariables.push(
    { id: 'tv-1', campaign_id: CAMPAIGN_ID, name: 'price', variable_type: 'LOCALIZED_VALUE', value: null, values_by_language: { en: '$10', fr: '10 €' } },
  )
  state.glossaryEntries.push(
    { id: 'glossary-1', scope_kind: 'CAMPAIGN', campaign_id: CAMPAIGN_ID, guild_id: null, source_term: 'Widget', behavior: 'FORCED_TRANSLATION', target_language_code: null, forced_translation: 'Gadgeto', match_mode: 'EXACT' },
  )
  state.campaigns[0].publication_mode = 'EVENT_TRIGGERED'
  state.triggers.push(
    { id: 'trigger-1', campaign_id: CAMPAIGN_ID, event_type: 'MESSAGE_CREATE', condition_ast: { op: 'AND', clauses: [{ op: 'EQUALS', path: 'author.bot', value: false }] }, max_causation_depth: 3, requires_message_content: false, version: 1 },
  )
  state.triggerSources.push(
    { id: 'trigger-source-1', guild_id: A, trigger_id: 'trigger-1', source_scope_kind: 'CATEGORY', discord_resource_id: CHANNEL },
  )
  await mockStage09(page, locale, state)
  await page.goto(`/guild/${A}/campaigns`)
  await expect(page.locator('html')).toHaveAttribute('lang', locale)
  await expect(page.getByRole('heading', { name: heading })).toBeVisible()
  await page.getByRole('button', { name: /Autumn sale/ }).click()
  await expect(page.locator('.campaign-detail')).toBeVisible()
  await page.locator('.campaign-triggers button').first().click()
  await page.locator('.trigger-sources #trigger-source-guild-id').fill(A)
  await expect(page.locator('.trigger-sources')).toBeVisible()
  await expect(page.getByText('PAUSED', { exact: true })).toHaveCount(0)
  await expect(page.getByText('INTERVENTION_REQUIRED', { exact: true })).toHaveCount(0)
  await expect(page.getByText(/^campaigns\./)).toHaveCount(0)
  await expect(page.getByText(/^errors\.campaigns\./)).toHaveCount(0)
})
