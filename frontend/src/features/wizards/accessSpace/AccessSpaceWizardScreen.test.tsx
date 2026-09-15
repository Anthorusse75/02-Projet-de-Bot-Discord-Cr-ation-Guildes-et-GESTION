import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import type { CapabilityDecision, DashboardCapabilities } from '../../../api/types'
import { discordSnowflake } from '../../../shared/discord-id'
import { AccessSpaceWizardScreen } from './AccessSpaceWizardScreen'

const apiRequestMock = vi.hoisted(() => vi.fn())
const navigateMock = vi.hoisted(() => vi.fn())

vi.mock('../../../api/client', () => ({
  apiRequest: (...args: unknown[]) => apiRequestMock(...args),
  ApiError: class ApiError extends Error {},
}))
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => navigateMock }
})
vi.mock('react-i18next', async () => {
  const { phase4WizardPacks } = await import('../../../localization/phase4WizardCatalog')
  const { phase4PoliciesPacks } = await import('../../../localization/phase4PoliciesCatalog')
  const { phase4Packs } = await import('../../../localization/phase4Catalog')
  const merged: Record<string, string> = { ...phase4Packs.en, ...phase4PoliciesPacks.en, ...phase4WizardPacks.en }
  return {
    useTranslation: () => ({
      t: (key: string, params: Record<string, string | number> = {}) => {
        const template = merged[key] ?? key
        return template.replace(/{{\s*([\w.-]+)\s*}}/g, (_, name: string) => String(params[name] ?? ''))
      },
    }),
  }
})

const guildId = discordSnowflake('700000000000000001')
const userId = discordSnowflake('700000000000000003')
const roleId = discordSnowflake('700000000000000011')
const can: CapabilityDecision = { outcome: 'CAN', causes: [], remediations: [] }

function capabilities(): DashboardCapabilities {
  return {
    guild_id: guildId,
    source: 'AUTHORIZATION_AND_LOCAL_CACHE',
    discord_rest_calls: 0,
    user_capabilities: { 'policies.read': can, 'policies.create': can, 'policies.update': can, 'policies.activate': can, 'plans.create': can, 'roles.write': can },
    scoped_capabilities: { scope_kind: 'GUILD', scope_id: '*', capabilities: {} },
    bot_operations: { CREATE_ROLE: { ...can, operation: 'CREATE_ROLE', required_permissions: [] } },
    coverage: 'FULL',
    completeness: 'FULL',
    freshness: 'FRESH',
  }
}

function Harness() {
  const guild = { guild_id: guildId, name: 'Alpha', owner: true, permissions: '8', installation_status: 'ACTIVE' }
  return <Outlet context={{
    me: { authenticated: true, user: { discord_user_id: userId, username: 'owner', global_name: null }, active_guild_id: guildId, csrf_token: 'csrf', policy_version: 1 },
    guild,
    guilds: [guild],
    connection: 'live',
    capabilities: capabilities(),
  }} />
}

function install() {
  apiRequestMock.mockReset()
  navigateMock.mockReset()
  apiRequestMock.mockImplementation((path: string, options: { method?: string } = {}) => {
    const method = options.method ?? 'GET'
    if (path.endsWith('/roles')) return Promise.resolve({ guild_id: guildId, source: 'LOCAL_CACHE', roles: [{ id: roleId, name: 'Managers', position: 5, permissions: '0', known_flags: [], unknown_bits: '0', managed: false, freshness: 'FRESH' }] })
    if (path.endsWith('/structure')) return Promise.resolve({ guild_id: guildId, source: 'LOCAL_CACHE', categories: [], root_channels: [] })
    if (path.endsWith('/logical-groups')) return Promise.resolve({ guild_id: guildId, groups: [] })
    if (path.endsWith('/policies') && method === 'GET') return Promise.resolve({ guild_id: guildId, policies: [] })
    return Promise.reject(new Error(`unexpected request ${method} ${path}`))
  })
}

async function renderWizard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/guild/${guildId}/wizards/access-space`]}>
        <Routes>
          <Route path="/guild/:guildId" element={<Harness />}>
            <Route path="wizards/access-space" element={<AccessSpaceWizardScreen />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  await screen.findByRole('heading', { name: 'Configure access to a space', level: 1 })
}

describe('AccessSpaceWizardScreen cancellation (REQ-WIZ-010)', () => {
  it('leaving before any draft was created triggers zero backend mutation', async () => {
    install()
    const user = userEvent.setup()
    await renderWizard()

    expect(screen.getByRole('button', { name: 'Leave without saving' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Leave without saving' }))

    expect(navigateMock).toHaveBeenCalledWith(`/guild/${guildId}/wizards`)
    const mutations = apiRequestMock.mock.calls.filter(([, options]) => options && ['POST', 'PATCH', 'PUT', 'DELETE'].includes((options as { method?: string }).method ?? ''))
    expect(mutations).toHaveLength(0)
  })

  it('never renders an Apply-to-Discord affordance anywhere on the page', async () => {
    install()
    await renderWizard()
    expect(screen.queryByRole('button', { name: /apply/i })).not.toBeInTheDocument()
  })
})
