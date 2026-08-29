import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from 'i18next'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { I18nextProvider } from 'react-i18next'
import { discordSnowflake } from '../../shared/discord-id'
import '../../localization/runtime'
import { TranslationWorkspace } from './TranslationWorkspace'

const guildId = discordSnowflake('700000000000000001')
const userId = discordSnowflake('700000000000000003')
const can = { outcome: 'CAN' as const, causes: [], remediations: [] }
let state: 'ready'|'loading'|'error' = 'ready'
let workspace = fixture()

vi.mock('../../api/queries', () => ({
  useTranslationWorkspace: () => ({ data: state === 'ready' ? workspace : undefined, isLoading: state === 'loading', isError: state === 'error', refetch: vi.fn() }),
}))

function fixture() {
  const languages = [
    { id: '11111111-1111-4111-8111-111111111111', guild_id: guildId, code: 'fr', display_name: 'French', emoji: null, enabled: true },
    { id: '22222222-2222-4222-8222-222222222222', guild_id: guildId, code: 'en', display_name: 'English', emoji: null, enabled: true },
  ]
  const frId = '11111111-1111-4111-8111-111111111111'; const enId = '22222222-2222-4222-8222-222222222222'
  const group = (id: string, name: string) => ({ id, guild_id: guildId, name, root_kind: 'CHANNEL_SET', routing_mode: 'HUB_AND_SPOKE', visibility_scope_id: 'scope', source_language_profile_id: frId, provider_binding_id: 'provider', status: 'ACTIVE', version: 2, languages, category_variants: [], channel_groups: [{ id: `${id}-channel-group`, logical_key: `${name}-guides`, display_name: `${name} guides`, source_language_profile_id: frId }], channel_variants: [{ id: `${id}-variant`, language_profile_id: frId, discord_channel_id: discordSnowflake('700000000000000010'), state: name === 'Guides' ? 'MISSING' : 'ACTIVE', translation_channel_group_id: `${id}-channel-group`, translation_category_variant_id: null }], routes: [{ id: `${id}-route`, source_language_profile_id: frId, destination_language_profile_id: enId, state: 'ACTIVE' }] })
  return { guild_id: guildId, source: 'POSTGRESQL_DURABLE_TRUTH' as const, discord_rest_calls: 0 as const, languages, groups: [group('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','Guides'), group('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb','Support')], providers: [{ id: 'provider', provider_type: 'existing_translation_bot', status: 'MANUAL_CONFIGURATION_REQUIRED', capabilities_json: {}, last_validated_at: null }], visibility_bindings: [{ id: 'binding', visibility_scope_id: 'scope', language_profile_id: frId, discord_role_id: discordSnowflake('700000000000000020'), state: 'ACTIVE' }], resource_language_policies: [{ id: 'policy', resource_type: 'CHANNEL' as const, discord_resource_id: discordSnowflake('700000000000000010'), explicit_language_profile_id: frId, inherit_language: false, visibility_policy: 'SCOPE_AND_LANGUAGE' as const, visibility_scope_id: 'scope' }] }
}

function Harness() {
  const guild = { guild_id: guildId, name: 'Alpha', owner: true, permissions: '8', installation_status: 'ACTIVE' }
  const capabilities = { guild_id: guildId, source: 'AUTHORIZATION_AND_LOCAL_CACHE' as const, discord_rest_calls: 0 as const, user_capabilities: { 'structure.read': can, 'structure.write': can, 'plans.create': can }, scoped_capabilities: { scope_kind: 'GUILD', scope_id: '*', capabilities: {} }, bot_operations: { CREATE_CHANNEL: { ...can, operation: 'CREATE_CHANNEL', required_permissions: [] } }, coverage: 'FULL', completeness: 'FULL', freshness: 'FRESH' }
  return <Outlet context={{ me: { authenticated: true, user: { discord_user_id: userId, username: 'owner', global_name: null }, active_guild_id: guildId, csrf_token: 'csrf', policy_version: 1 }, guild, guilds: [guild], connection: 'live', capabilities }} />
}

function mounted() { return render(<I18nextProvider i18n={i18n}><QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={[`/guild/${guildId}/translations`]}><Routes><Route path="/guild/:guildId" element={<Harness />}><Route path="translations" element={<TranslationWorkspace />} /><Route path="clone" element={<div>clone-target</div>} /></Route></Routes></MemoryRouter></QueryClientProvider></I18nextProvider>) }

describe('STAGE 08 translation workspace', () => {
  beforeEach(async () => { state = 'ready'; workspace = fixture(); await i18n.changeLanguage('en') })
  it('keeps two FR/EN groups independent and exposes manual provider, drift, visibility and capacity', () => {
    mounted()
    expect(screen.getByRole('heading', { name: 'Translation workspace' })).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Guides' })).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Support' })).toBeVisible()
    expect(screen.getByText('Manual configuration required')).toBeVisible()
    expect(screen.getByText('Missing')).toBeVisible()
    expect(screen.getByText(/Scope and language/)).toBeVisible()
    expect(screen.getByText('1 of 250 reusable roles')).toBeVisible()
  })
  it('opens all four multilingual actions with a mounted right drag and retains keyboard buttons', () => {
    mounted(); const card = screen.getByRole('heading', { name: 'Guides' }).closest<HTMLElement>('article'); if (!card) throw new Error('group card missing')
    fireEvent.pointerDown(card, { pointerId: 8, button: 2, pointerType: 'mouse', clientX: 0, clientY: 0 }); fireEvent.pointerMove(card, { pointerId: 8, button: 2, clientX: 12, clientY: 0 }); fireEvent.pointerUp(card, { pointerId: 8, button: 2, clientX: 12, clientY: 0 })
    expect(screen.getByRole('menu', { name: 'Available actions' })).toBeVisible()
    for (const label of ['Create variant','Link existing variant','Clone independently','Preview topology']) expect(screen.getAllByText(label).length).toBeGreaterThan(0)
  })
  it('renders localized French labels without raw enums or raw keys', async () => {
    await i18n.changeLanguage('fr'); mounted()
    expect(screen.getByRole('heading', { name: 'Espace de traduction' })).toBeVisible()
    expect(screen.queryByText('HUB_AND_SPOKE')).not.toBeInTheDocument()
    expect(document.body.textContent).not.toContain('translations.')
  })
  it('renders loading, error and empty states', () => {
    state = 'loading'; const first = mounted(); expect(screen.getByRole('status')).toBeVisible(); first.unmount()
    state = 'error'; const second = mounted(); expect(screen.getByRole('alert')).toBeVisible(); second.unmount()
    state = 'ready'; workspace = { ...fixture(), groups: [] }; mounted(); expect(screen.getByText('No translation group exists for this server.')).toBeVisible()
  })
})
