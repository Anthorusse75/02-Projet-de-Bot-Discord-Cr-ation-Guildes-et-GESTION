import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from 'i18next'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { I18nextProvider } from 'react-i18next'
import { discordSnowflake } from '../../shared/discord-id'
import '../../localization/runtime'
import { CampaignCenter } from './CampaignCenter'

const guildId = discordSnowflake('700000000000000001')
const otherGuildId = discordSnowflake('700000000000000002')
const userId = discordSnowflake('700000000000000003')
const channelId = '700000000000000010'

type Campaign = Record<string, unknown>
type MockCall = { path: string; method: string; body?: unknown }

vi.mock('../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/client')>()
  return { ...actual, apiRequest: vi.fn() }
})

import { apiRequest } from '../../api/client'
const apiRequestMock = vi.mocked(apiRequest)

function campaign(overrides: Partial<Campaign> = {}): Campaign {
  return {
    id: '99999999-9999-4999-8999-999999999901', owner_discord_user_id: userId, logical_campaign_key: 'k',
    name: 'Autumn sale', source_language_code: 'en', message_model: { content: 'Hello there', embeds: [], action_rows: [] },
    allowed_mentions_policy: {}, publication_mode: 'IMMEDIATE', attachment_policy: 'PRESERVE_EXISTING',
    lifecycle_status: 'DRAFT', version: 1, created_at: null, updated_at: null, ...overrides,
  }
}

function buildState() {
  return {
    campaigns: [] as Campaign[],
    targets: [] as Campaign[],
    deliveries: [] as Campaign[],
    glossaryEntries: [] as Campaign[],
    calls: [] as MockCall[],
  }
}
let state = buildState()

function installApiRequestMock() {
  apiRequestMock.mockReset()
  apiRequestMock.mockImplementation(async (path: string, options: Record<string, unknown> = {}) => {
    const method = String(options.method ?? 'GET')
    const body = options.body
    state.calls.push({ path, method, body })
    if (path === '/api/v1/retention-policy' && method === 'GET') {
      return { retention_days: 90, min_retention_days: 1, max_retention_days: 3650, purged_delivery_statuses: ['SENT', 'FAILED'] }
    }
    if (path === '/api/v1/campaigns' && method === 'GET') return { campaigns: state.campaigns }
    if (path === '/api/v1/campaigns' && method === 'POST') {
      const input = body as Record<string, unknown>
      const created = campaign({
        id: `created-${state.campaigns.length + 1}`, name: input.name, source_language_code: input.source_language_code,
        message_model: input.message_model, publication_mode: input.publication_mode,
      })
      state.campaigns.push(created)
      return { created: true, campaign: created }
    }
    const patchMatch = path.match(/^\/api\/v1\/campaigns\/([^/]+)$/)
    if (patchMatch && method === 'PATCH') {
      const id = patchMatch[1]
      const input = body as Record<string, unknown>
      state.campaigns = state.campaigns.map((item) => item.id === id
        ? { ...item, message_model: input.message_model ?? item.message_model, allowed_mentions_policy: input.allowed_mentions_policy ?? item.allowed_mentions_policy, version: Number(item.version) + 1 }
        : item)
      return state.campaigns.find((item) => item.id === id)
    }
    if (path.endsWith('/targets') && method === 'GET') return { targets: state.targets }
    if (path.endsWith('/targets') && method === 'POST') {
      const input = body as Record<string, unknown>
      const target = { id: `target-${state.targets.length + 1}`, guild_id: input.guild_id, campaign_id: path.split('/')[4], target_kind: input.target_kind, discord_channel_id: input.discord_channel_id, translation_group_id: null, translation_publication_mode: null, selected_language_profile_ids: [], logical_group_id: null }
      state.targets.push(target)
      return { target, bot_send_preflight_ok: true }
    }
    if (path.endsWith('/schedule') && method === 'POST') {
      const input = body as Record<string, unknown>
      return { id: 'schedule-1', campaign_id: path.split('/')[4], schedule_kind: input.schedule_kind, fire_at: input.fire_at ?? null, rrule: input.rrule ?? null, timezone: input.timezone ?? null, starts_at: input.starts_at ?? null, misfire_policy: 'SKIP_MISSED', dst_nonexistent_policy: 'SHIFT_FORWARD', dst_ambiguous_policy: 'EARLIEST', catch_up_bound: 1, next_fire_at: '2026-09-05T12:00:00Z', version: 1 }
    }
    if (path.endsWith('/simulate') && method === 'POST') {
      return {
        destinations: [{ guild_id: guildId, discord_channel_id: channelId, language_profile_id: null, ready: true, blocked_reason: null, translation_state: 'SOURCE', delivery_executable: true }],
        total_destinations: 1, ready_destinations: 1, blocked_destinations: 0, estimated_delivery_count: 1, blockers: {}, message_content_warnings: [], undeclared_template_variable_names: [], matched_glossary_terms: [],
      }
    }
    const lifecycleMatch = path.match(/^\/api\/v1\/campaigns\/([^/]+)\/(activate|pause|resume|cancel)$/)
    if (lifecycleMatch && method === 'POST') {
      const [, id, action] = lifecycleMatch
      const next = action === 'activate' ? 'ACTIVE_RUNNING' : action === 'pause' ? 'PAUSED' : action === 'resume' ? 'ACTIVE_RUNNING' : 'CANCELLED'
      state.campaigns = state.campaigns.map((item) => item.id === id ? { ...item, lifecycle_status: next } : item)
      const updated = state.campaigns.find((item) => item.id === id)
      return action === 'activate' ? { campaign: updated, durable_work: { occurrence_created: false, deliveries_created: 0, deliveries_routed: 0, is_fully_healthy: true } } : updated
    }
    if (path.endsWith('/deliveries') && method === 'GET') return { deliveries: state.deliveries }
    const variantMatch = path.match(/\/variants\/([^/]+)$/)
    if (variantMatch && method === 'GET') {
      return { campaign_id: path.split('/')[4], target_language_code: decodeURIComponent(variantMatch[1] ?? ''), outcome: 'MISSING', current_source_fingerprint: 'fp', approved_variant: null }
    }
    if (path.includes('/variants/') && path.endsWith('/approve') && method === 'POST') {
      const input = body as Record<string, unknown>
      return { id: 'variant-1', campaign_id: path.split('/')[4], target_language_code: 'fr', source_fingerprint: 'fp', localized_message_model: input.localized_message_model, approved_by_discord_user_id: userId, approved_at: '2026-09-01T00:00:00Z' }
    }
    if (path.endsWith('/structure') && method === 'GET') {
      return { guild_id: guildId, source: 'LOCAL_CACHE', discord_rest_calls: 0, categories: [], root_channels: [{ guild_id: guildId, id: channelId, type: 0, name: 'general', position: 0, parent_id: null, resource_kind: 'CHANNEL', observability: 'VISIBLE', freshness: 'FRESH', data_assertion: 'OBSERVED' }] }
    }
    const campaignGlossaryMatch = path.match(/^\/api\/v1\/campaigns\/([^/]+)\/glossary$/)
    if (campaignGlossaryMatch && method === 'GET') return { glossary_entries: state.glossaryEntries.filter((entry) => entry.campaign_id === campaignGlossaryMatch[1]) }
    const guildGlossaryMatch = path.match(/^\/api\/v1\/guilds\/([^/]+)\/glossary$/)
    if (guildGlossaryMatch && method === 'GET') return { glossary_entries: state.glossaryEntries.filter((entry) => entry.guild_id === guildGlossaryMatch[1]) }
    if (path === '/api/v1/glossary' && method === 'GET') return { glossary_entries: state.glossaryEntries.filter((entry) => entry.scope_kind === 'GLOBAL_USER') }
    if (path === '/api/v1/glossary' && method === 'POST') {
      const input = body as Record<string, unknown>
      const created = {
        id: `glossary-${state.glossaryEntries.length + 1}`, scope_kind: input.scope_kind, source_term: input.source_term, behavior: input.behavior,
        campaign_id: input.campaign_id ?? null, guild_id: input.guild_id ?? null, target_language_code: input.target_language_code ?? null,
        forced_translation: input.forced_translation ?? null, match_mode: input.match_mode,
      }
      state.glossaryEntries.push(created)
      return created
    }
    const glossaryDeleteMatch = path.match(/^\/api\/v1\/glossary\/([^/]+)$/)
    if (glossaryDeleteMatch && method === 'DELETE') {
      state.glossaryEntries = state.glossaryEntries.filter((entry) => entry.id !== glossaryDeleteMatch[1])
      return undefined
    }
    throw new Error(`unhandled apiRequest path in test: ${method} ${path}`)
  })
}

function Harness() {
  const guild = { guild_id: guildId, name: 'Alpha', owner: true, permissions: '8', installation_status: 'ACTIVE' }
  const otherGuild = { guild_id: otherGuildId, name: 'Beta', owner: true, permissions: '8', installation_status: 'ACTIVE' }
  return <Outlet context={{ me: { authenticated: true, user: { discord_user_id: userId, username: 'owner', global_name: null }, active_guild_id: guildId, csrf_token: 'csrf', policy_version: 1 }, guild, guilds: [guild, otherGuild], connection: 'live', capabilities: undefined }} />
}

function mounted() {
  return render(<I18nextProvider i18n={i18n}><QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={[`/guild/${guildId}/campaigns`]}><Routes><Route path="/guild/:guildId" element={<Harness />}><Route path="campaigns" element={<CampaignCenter />} /></Route></Routes></MemoryRouter></QueryClientProvider></I18nextProvider>)
}

describe('STAGE 09 campaign center', () => {
  beforeEach(async () => { state = buildState(); installApiRequestMock(); await i18n.changeLanguage('en') })

  it('renders the empty state when no campaign exists', async () => {
    mounted()
    expect(await screen.findByRole('heading', { name: 'Message & campaign center' })).toBeVisible()
    expect(screen.getByText('No campaign exists yet.')).toBeVisible()
  })

  it('creates a campaign through the real endpoint and selects it', async () => {
    mounted()
    await screen.findByRole('heading', { name: 'Message & campaign center' })
    fireEvent.change(screen.getByLabelText('Campaign name'), { target: { value: 'Autumn sale' } })
    fireEvent.change(screen.getByLabelText('Message content'), { target: { value: 'Hello everyone' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create campaign' }))
    await waitFor(() => expect(state.campaigns).toHaveLength(1))
    expect(state.calls.find((call) => call.path === '/api/v1/campaigns' && call.method === 'POST')?.body).toMatchObject({ name: 'Autumn sale', publication_mode: 'IMMEDIATE' })
    expect(await screen.findByRole('heading', { name: 'Campaign detail' })).toBeVisible()
    const detail = screen.getByRole('heading', { name: 'Campaign detail' }).closest('section')
    if (!detail) throw new Error('detail section missing')
    expect(within(detail).getByText('Draft')).toBeVisible()
  })

  it('authors an embed and a button as part of the campaign message model (mission section 9)', async () => {
    mounted()
    await screen.findByRole('heading', { name: 'Message & campaign center' })
    fireEvent.change(screen.getByLabelText('Campaign name'), { target: { value: 'Autumn sale' } })
    fireEvent.change(screen.getByLabelText('Message content'), { target: { value: 'Hello everyone' } })

    fireEvent.click(screen.getByRole('button', { name: 'Add embed' }))
    fireEvent.change(screen.getByLabelText('Embed title'), { target: { value: 'Launch' } })
    fireEvent.change(screen.getByLabelText('Embed description'), { target: { value: 'Big news' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add field' }))
    fireEvent.change(screen.getByLabelText('Field name'), { target: { value: 'Starts' } })
    fireEvent.change(screen.getByLabelText('Field value'), { target: { value: 'Today' } })

    fireEvent.click(screen.getByRole('button', { name: 'Add button row' }))
    fireEvent.click(screen.getByRole('button', { name: 'Add button' }))
    fireEvent.change(screen.getByLabelText('Button label'), { target: { value: 'Confirm' } })
    fireEvent.change(screen.getByLabelText('Button custom ID'), { target: { value: 'confirm-launch' } })

    fireEvent.click(screen.getByRole('button', { name: 'Create campaign' }))
    await waitFor(() => expect(state.campaigns).toHaveLength(1))
    const body = state.calls.find((call) => call.path === '/api/v1/campaigns' && call.method === 'POST')?.body as { message_model: { embeds: Array<Record<string, unknown>>; action_rows: Array<{ buttons: Array<Record<string, unknown>> }> } }
    expect(body.message_model.embeds).toHaveLength(1)
    const embed = body.message_model.embeds[0]
    if (!embed) throw new Error('embed missing')
    expect(embed).toMatchObject({ title: 'Launch', description: 'Big news' })
    expect(embed.fields).toMatchObject([{ name: 'Starts', value: 'Today' }])
    const button = body.message_model.action_rows[0]?.buttons[0]
    if (!button) throw new Error('button missing')
    expect(button).toMatchObject({ label: 'Confirm', style: 'PRIMARY', custom_id: 'confirm-launch' })
  })

  it('adds a real channel target resolved from the destination Guild structure, runs the preview, and activates the campaign', async () => {
    state.campaigns.push(campaign())
    mounted()
    const card = await screen.findByRole('button', { name: /Autumn sale/ })
    fireEvent.click(card)
    await screen.findByRole('heading', { name: 'Campaign detail' })
    const detail = screen.getByRole('heading', { name: 'Campaign detail' }).closest('section')
    if (!detail) throw new Error('detail section missing')

    fireEvent.change(screen.getByLabelText('Destination server'), { target: { value: guildId } })
    await waitFor(() => expect(within(screen.getByLabelText('Destination channel')).getByText('general')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('Destination channel'), { target: { value: channelId } })
    fireEvent.click(screen.getByRole('button', { name: 'Add target' }))
    await waitFor(() => expect(state.targets).toHaveLength(1))
    expect(state.targets[0]).toMatchObject({ guild_id: guildId, discord_channel_id: channelId, target_kind: 'CHANNEL' })

    fireEvent.click(screen.getByRole('button', { name: 'Run preview' }))
    expect(await screen.findByText('1 of 1 destinations ready (1 estimated deliveries)')).toBeVisible()

    fireEvent.click(screen.getByRole('button', { name: 'Activate' }))
    await waitFor(() => expect(within(detail).getByText('Active')).toBeVisible())
    expect(state.calls.some((call) => call.path.endsWith('/activate'))).toBe(true)
  })

  it('reads delivery history and checks + approves an approved variant', async () => {
    state.campaigns.push(campaign({ lifecycle_status: 'ACTIVE_RUNNING' }))
    state.deliveries.push({ id: 'd1', guild_id: guildId, campaign_id: 'x', occurrence_id: 'o1', target_id: 't1', language_profile_id: null, delivery_key: 'k', discord_channel_id: channelId, status: 'SENT', discord_message_id: '1', attempt_count: 1, last_error: null, created_at: null, updated_at: '2026-09-01T00:00:00Z' })
    mounted()
    fireEvent.click(await screen.findByRole('button', { name: /Autumn sale/ }))
    await screen.findByRole('heading', { name: 'Campaign detail' })
    expect(await screen.findByText('Sent')).toBeVisible()

    fireEvent.change(screen.getByLabelText('Target language code'), { target: { value: 'fr' } })
    fireEvent.click(screen.getByRole('button', { name: 'Check variant' }))
    expect(await screen.findByText('Missing')).toBeVisible()
    fireEvent.change(screen.getByLabelText('Localized content'), { target: { value: 'Bonjour à tous' } })
    fireEvent.click(screen.getByRole('button', { name: 'Approve variant' }))
    await waitFor(() => expect(state.calls.some((call) => call.path.endsWith('/variants/fr/approve'))).toBe(true))
    expect(await screen.findByText('Variant approved.')).toBeVisible()
  })

  it('renders localized French labels without raw enums or raw keys', async () => {
    state.campaigns.push(campaign({ lifecycle_status: 'PAUSED' }))
    await i18n.changeLanguage('fr')
    mounted()
    expect(await screen.findByRole('heading', { name: 'Centre de messages et campagnes' })).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: /Autumn sale/ }))
    await screen.findByRole('heading', { name: 'Détail de la campagne' })
    const detail = screen.getByRole('heading', { name: 'Détail de la campagne' }).closest('section')
    if (!detail) throw new Error('detail section missing')
    expect(within(detail).getByText('En pause')).toBeVisible()
    expect(screen.queryByText('PAUSED')).not.toBeInTheDocument()
    expect(document.body.textContent).not.toContain('campaigns.')
  })
})
