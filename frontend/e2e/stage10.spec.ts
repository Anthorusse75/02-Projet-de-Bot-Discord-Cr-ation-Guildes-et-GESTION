import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

const A = '700000000000000001'
const B = '700000000000000002'
const USER = '700000000000000003'
const CHANNEL = '700000000000000010'
const PLAN = '11111111-1111-4111-8111-111111111111'
const CAMPAIGN = '99999999-9999-4999-8999-999999999901'

type GlobalState = {
  authenticated: boolean
  locale: string
  failStructureOnce: boolean
  applied: boolean
  planStatus: string
  planVersion: number
  structureChannelCount: number
}

const can = { outcome: 'CAN', causes: [], remediations: [] }

function plan(state: GlobalState) {
  return {
    id: PLAN,
    guild_id: A,
    status: state.planStatus,
    state_version: state.planVersion,
    plan_hash: 'a'.repeat(64),
    risk_level: 'MEDIUM',
    impact: {},
    reinforced_confirmation_required: false,
    created_at: '2026-09-11T00:00:00Z',
    updated_at: '2026-09-11T00:00:00Z',
    error_code: null,
  }
}

function capabilities(guildId: string) {
  const user = {
    'structure.read': can,
    'structure.write': can,
    'plans.create': can,
    'plans.apply': can,
    'permissions.read': can,
  }
  return {
    guild_id: guildId,
    source: 'AUTHORIZATION_AND_LOCAL_CACHE',
    discord_rest_calls: 0,
    user_capabilities: user,
    scoped_capabilities: { scope_kind: 'GUILD', scope_id: '*', capabilities: user },
    bot_operations: { CREATE_CHANNEL: can, REORDER_CHANNELS: can },
    coverage: 'FULL',
    completeness: 'FULL',
    freshness: 'FRESH',
  }
}

function structure(guildId: string) {
  return {
    guild_id: guildId,
    source: 'LOCAL_CACHE',
    discord_rest_calls: 0,
    categories: [],
    root_channels: [
      {
        guild_id: guildId,
        id: CHANNEL,
        type: 0,
        name: 'general',
        position: 0,
        parent_id: null,
        resource_kind: 'DISCORD_RESOURCE',
        observability: 'VISIBLE',
        freshness: 'FRESH',
        data_assertion: 'CURRENT_CONFIRMED',
      },
    ],
  }
}

function largeStructure(guildId: string, count: number) {
  const fixture = structure(guildId).root_channels[0]
  return {
    ...structure(guildId),
    root_channels: Array.from({ length: count }, (_, index) => ({
      ...fixture,
      id: String(700000000000001000n + BigInt(index)),
      name: `channel-${index}`,
      position: index,
    })),
  }
}

function translationWorkspace() {
  return {
    guild_id: A,
    source: 'DURABLE_TOPOLOGY_AND_LOCAL_DISCORD_CACHE',
    discord_rest_calls: 0,
    cache_coverage: {
      mode: 'FULL',
      freshness: 'FRESH',
      roles_complete: true,
      channels_complete: true,
      members_complete: true,
      state_version: 1,
    },
    languages: [
      {
        id: 'lang-en',
        guild_id: A,
        code: 'en',
        display_name: 'English',
        emoji: null,
        enabled: true,
      },
      {
        id: 'lang-fr',
        guild_id: A,
        code: 'fr',
        display_name: 'French',
        emoji: null,
        enabled: true,
      },
    ],
    groups: [],
    providers: [],
    visibility_bindings: [],
    resource_language_policies: [],
  }
}

async function mockGlobalDashboard(page: Page, state: GlobalState) {
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    const method = route.request().method()
    if (path === '/api/v1/ui/locales') {
      return route.fulfill({
        json: {
          catalog_version: 'did-ui-v2',
          locales: ['en', 'fr', 'de', 'es'].map((code) => ({
            locale_code: code,
            display_name: code.toUpperCase(),
            flag_code: code,
            direction: 'ltr',
          })),
        },
      })
    }
    if (path.startsWith('/api/v1/ui/locales/')) {
      return route.fulfill({
        status: 404,
        json: {
          error: {
            code: 'NOT_FOUND',
            message_key: 'errors.resource.notFound',
            params: {},
            request_id: 'stage10-e2e',
          },
        },
      })
    }
    if (path === '/api/v1/me') {
      if (!state.authenticated) {
        return route.fulfill({
          status: 401,
          json: {
            error: {
              code: 'NOT_AUTHENTICATED',
              message_key: 'errors.auth.required',
              params: {},
              request_id: 'stage10-e2e',
            },
          },
        })
      }
      return route.fulfill({
        json: {
          authenticated: true,
          user: { discord_user_id: USER, username: 'owner', global_name: 'Owner' },
          active_guild_id: null,
          csrf_token: 'csrf',
          policy_version: 1,
        },
      })
    }
    if (path === '/api/v1/me/preferences') {
      return route.fulfill({
        json:
          method === 'GET'
            ? { ui_locale_override_code: state.locale, timezone: null }
            : route.request().postDataJSON(),
      })
    }
    if (path === '/api/v1/guilds') {
      return route.fulfill({
        json: {
          guilds: [
            {
              guild_id: A,
              name: 'Alpha',
              owner: true,
              permissions: '8',
              installation_status: 'ACTIVE',
            },
            {
              guild_id: B,
              name: 'Beta',
              owner: true,
              permissions: '8',
              installation_status: 'ACTIVE',
            },
          ],
        },
      })
    }
    if (path.endsWith('/select')) {
      return route.fulfill({
        json: { guild_id: path.split('/')[4], csrf_token: 'next', policy_version: 2 },
      })
    }
    if (path.endsWith('/dashboard-capabilities')) {
      return route.fulfill({ json: capabilities(path.split('/')[4] ?? A) })
    }
    if (path.endsWith('/structure')) {
      if (state.failStructureOnce) {
        return route.fulfill({ status: 503, body: 'controlled failure' })
      }
      const guildId = path.split('/')[4] ?? A
      return route.fulfill({
        json:
          state.structureChannelCount === 1
            ? structure(guildId)
            : largeStructure(guildId, state.structureChannelCount),
      })
    }
    if (path.endsWith('/permissions/explain') && method === 'POST') {
      return route.fulfill({
        json: {
          effective_bits: '1024',
          warnings: [],
          trace: [
            {
              step: 'BASE_EVERYONE',
              reason_key: 'permissions.trace.baseEveryone',
              after: '1024',
            },
          ],
          outcome: 'CAN',
        },
      })
    }
    if (/\/guilds\/[^/]+\/plans$/.test(path) && method === 'GET') {
      return route.fulfill({ json: { guild_id: A, plans: [plan(state)] } })
    }
    if (path.endsWith('/validate') && method === 'POST') {
      state.planStatus = 'VALIDATED'
      state.planVersion = 6
      return route.fulfill({
        json: {
          plan: plan(state),
          preflight: { allowed: true, errors: [], warnings: [], checked_capabilities: [] },
        },
      })
    }
    if (path.endsWith('/confirm') && method === 'POST') {
      state.planStatus = 'CONFIRMED'
      state.planVersion = 7
      return route.fulfill({ json: plan(state) })
    }
    if (path.endsWith('/apply') && method === 'POST') {
      state.applied = true
      return route.fulfill({
        status: 202,
        json: {
          guild_id: A,
          plan_id: PLAN,
          job_id: '44444444-4444-4444-8444-444444444444',
        },
      })
    }
    if (path.endsWith('/progress')) {
      return route.fulfill({
        json: {
          events: state.applied
            ? [
                {
                  sequence: 1,
                  plan_status: 'SUCCEEDED',
                  completed_operations: 2,
                  total_operations: 2,
                  message_key: 'plans.progress.succeeded',
                  params: {},
                },
              ]
            : [],
        },
      })
    }
    if (path === '/api/v1/transfers' && method === 'POST') {
      return route.fulfill({
        status: 201,
        json: {
          transfer: { status: 'COMPILED' },
          plan: { id: '33333333-3333-4333-8333-333333333333' },
        },
      })
    }
    if (path.endsWith('/translation-workspace')) {
      return route.fulfill({ json: translationWorkspace() })
    }
    if (path.endsWith('/logical-groups')) {
      return route.fulfill({ json: { guild_id: A, resource_kind: 'DID_LOGICAL_RESOURCE', groups: [] } })
    }
    if (path === '/api/v1/retention-policy') {
      return route.fulfill({
        json: {
          retention_days: 90,
          min_retention_days: 1,
          max_retention_days: 3650,
          purged_delivery_statuses: ['SENT', 'FAILED'],
        },
      })
    }
    if (path === '/api/v1/campaigns' && method === 'GET') {
      return route.fulfill({
        json: {
          campaigns: [
            {
              id: CAMPAIGN,
              owner_discord_user_id: USER,
              logical_campaign_key: 'stage10-global',
              name: 'Global acceptance',
              source_language_code: 'en',
              message_model: { content: 'Hello everyone', embeds: [], action_rows: [] },
              allowed_mentions_policy: {},
              publication_mode: 'IMMEDIATE',
              attachment_policy: 'PRESERVE_EXISTING',
              lifecycle_status: 'DRAFT',
              version: 1,
              created_at: '2026-09-11T00:00:00Z',
              updated_at: '2026-09-11T00:00:00Z',
            },
          ],
        },
      })
    }
    if (path.endsWith('/targets')) return route.fulfill({ json: { targets: [] } })
    if (path.endsWith('/deliveries')) return route.fulfill({ json: { deliveries: [] } })
    if (path.endsWith('/template-variables')) {
      return route.fulfill({ json: { template_variables: [] } })
    }
    if (path.endsWith('/glossary') || path === '/api/v1/glossary') {
      return route.fulfill({ json: { glossary_entries: [] } })
    }
    if (path.endsWith('/triggers')) return route.fulfill({ json: { triggers: [] } })
    return route.fulfill({
      status: 404,
      json: {
        error: {
          code: 'NOT_FOUND',
          message_key: 'errors.resource.notFound',
          params: {},
          request_id: 'stage10-e2e',
        },
      },
    })
  })
}

function state(overrides: Partial<GlobalState> = {}): GlobalState {
  return {
    authenticated: true,
    locale: 'en',
    failStructureOnce: false,
    applied: false,
    planStatus: 'DRAFT',
    planVersion: 5,
    structureChannelCount: 1,
    ...overrides,
  }
}

test('@a11y global login-to-campaign critical journey crosses every product plane', async ({
  page,
}) => {
  const current = state({ authenticated: false })
  await mockGlobalDashboard(page, current)

  await page.goto('/login')
  await expect(page.getByRole('link', { name: 'Continue with Discord' })).toHaveAttribute(
    'href',
    '/auth/discord/login',
  )
  current.authenticated = true
  await page.reload()
  await expect(page).toHaveURL(/\/guilds$/)
  await page.locator('.guild-list li').filter({ hasText: 'Alpha' }).getByRole('button').click()
  await expect(page).toHaveURL(new RegExp(`/guild/${A}/structure$`))
  await expect(page.getByRole('tree')).toContainText('general')

  await page.keyboard.press('Control+k')
  await expect(page.getByRole('dialog', { name: 'Command palette' })).toBeVisible()
  await page.keyboard.press('Escape')

  await page.getByRole('link', { name: 'Permissions' }).click()
  await page.getByLabel('Discord subject ID').fill(USER)
  await page.getByLabel('Discord resource ID').fill(CHANNEL)
  await page.getByRole('button', { name: 'Why access?' }).click()
  await expect(page.getByText('Effective permissions: 1024')).toBeVisible()

  await page.getByRole('link', { name: 'Plans' }).click()
  await page.locator('.plan-card').click()
  await page.getByRole('button', { name: 'Run preflight' }).click()
  await page.getByRole('button', { name: 'Confirm plan' }).click()
  await page.getByRole('button', { name: 'Queue apply' }).click()
  await expect(page.getByText('Plan applied and verified.')).toBeVisible({ timeout: 4_000 })

  await page.getByRole('link', { name: 'Clone' }).click()
  await page.getByLabel('Discord resource ID').fill(CHANNEL)
  await page.getByLabel('Destination server').selectOption(B)
  await page.getByRole('button', { name: 'Preview' }).click()
  await expect(page.getByRole('status')).toContainText('Transfer preview created')

  await page.getByRole('link', { name: 'Translations' }).click()
  await expect(page.getByRole('heading', { name: 'Translation workspace' })).toBeVisible()
  await expect(page.getByText('French')).toBeVisible()

  await page.getByRole('link', { name: 'Campaigns' }).click()
  await expect(page.getByRole('heading', { name: 'Message & campaign center' })).toBeVisible()
  await page.getByRole('button', { name: /Global acceptance/ }).click()
  await expect(page.getByRole('heading', { name: 'Campaign detail' })).toBeVisible()

  const results = await new AxeBuilder({ page }).exclude('.locale-flag').analyze()
  expect(
    results.violations.filter((item) => ['serious', 'critical'].includes(item.impact ?? '')),
  ).toEqual([])
})

test('global read failure remains explicit and keyboard retry recovers', async ({ page }) => {
  const current = state({ failStructureOnce: true })
  await mockGlobalDashboard(page, current)

  await page.goto(`/guild/${A}/structure`)
  await expect(page.getByRole('alert')).toContainText('The service is unreachable')
  current.failStructureOnce = false
  await page.getByRole('button', { name: 'Try again' }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('tree')).toContainText('general')
})

test('@performance 500-channel structure renders within the browser budget', async ({ page }) => {
  await mockGlobalDashboard(page, state({ structureChannelCount: 500 }))
  const started = performance.now()
  await page.goto(`/guild/${A}/structure`)
  await expect(page.getByRole('treeitem')).toHaveCount(500)
  const durationMs = performance.now() - started
  expect(durationMs).toBeLessThan(5_000)
})

const localizedHeadings = {
  en: ['Discord structure', 'Permission explorer', 'Plans and jobs', 'Translation workspace', 'Message & campaign center'],
  fr: ['Structure Discord', 'Explorateur de permissions', 'Plans et jobs', 'Espace de traduction', 'Centre de messages et campagnes'],
  de: ['Discord-Struktur', 'Berechtigungs-Explorer', 'Pläne und Jobs', 'Uebersetzungsbereich', 'Nachrichten- und Kampagnenzentrale'],
  es: ['Estructura de Discord', 'Explorador de permisos', 'Planes y trabajos', 'Espacio de traduccion', 'Centro de mensajes y campañas'],
} as const

for (const [locale, headings] of Object.entries(localizedHeadings)) {
  test(`global critical surfaces remain localized (${locale})`, async ({ page }) => {
    await mockGlobalDashboard(page, state({ locale }))
    for (const [route, heading] of [
      ['structure', headings[0]],
      ['permissions', headings[1]],
      ['plans', headings[2]],
      ['translations', headings[3]],
      ['campaigns', headings[4]],
    ]) {
      await page.goto(`/guild/${A}/${route}`)
      await expect(page.locator('html')).toHaveAttribute('lang', locale)
      await expect(page.getByRole('heading', { name: heading })).toBeVisible()
    }
  })
}
