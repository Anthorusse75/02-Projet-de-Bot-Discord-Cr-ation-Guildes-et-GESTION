import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import type { CapabilityDecision, DashboardCapabilities } from '../../api/types'
import { discordSnowflake } from '../../shared/discord-id'
import { BunnyTestProvider } from '../../test/BunnyTestProvider'
import { RolesScreen } from './RolesScreen'

const apiRequestMock = vi.hoisted(() => vi.fn())

vi.mock('../../api/client', () => ({ apiRequest: (...args: unknown[]) => apiRequestMock(...args) }))
vi.mock('react-i18next', async () => {
  const { phase4Packs } = await import('../../localization/phase4Catalog')
  const { bunnyRolesPacks } = await import('../../localization/bunnyRolesCatalog')
  const { phase4Overrides } = await import('../../localization/phase4Overrides')
  const messages = { ...phase4Packs.en, ...phase4Overrides.en, ...bunnyRolesPacks.en } as Record<string, string>
  return {
    useTranslation: () => ({
      t: (key: string, params: Record<string, string | number> = {}) => {
        const template = messages[key] ?? key
        return template.replace(/{{\s*([\w.-]+)\s*}}/g, (_, name: string) => String(params[name] ?? ''))
      },
    }),
  }
})
vi.mock('../../api/queries', () => ({
  useRoles: () => ({
    data: {
      roles: [
        { id: discordSnowflake('700000000000000010'), name: 'DID Bot', position: 5, permissions: '268435456', known_flags: ['MANAGE_ROLES'], unknown_bits: '0', managed: true, freshness: 'FRESH' },
        { id: discordSnowflake('700000000000000012'), name: 'bots', position: 4, permissions: '0', known_flags: [], unknown_bits: '0', managed: false, freshness: 'FRESH' },
      ],
    },
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
}))

const guildId = discordSnowflake('700000000000000001')
const can = { outcome: 'CAN' as const, causes: [], remediations: [] }

function capabilities(decision: CapabilityDecision): DashboardCapabilities {
  return {
    guild_id: guildId,
    source: 'AUTHORIZATION_AND_LOCAL_CACHE',
    discord_rest_calls: 0,
    user_capabilities: { 'roles.write': can, 'plans.create': can },
    scoped_capabilities: { scope_kind: 'GUILD', scope_id: '*', capabilities: {} },
    bot_operations: {
      MANAGE_ROLE: { ...decision, operation: 'MANAGE_ROLE', required_permissions: ['MANAGE_ROLES'] },
      REORDER_ROLES: { ...decision, operation: 'REORDER_ROLES', required_permissions: ['MANAGE_ROLES'] },
      CREATE_ROLE: { ...can, operation: 'CREATE_ROLE', required_permissions: ['MANAGE_ROLES'] },
    },
    coverage: 'FULL',
    completeness: 'FULL',
    freshness: 'FRESH',
  }
}

function Harness() {
  const guild = { guild_id: guildId, name: 'Alpha', owner: true, permissions: '8', installation_status: 'ACTIVE' }
  return <Outlet context={{
    me: { authenticated: true, user: { discord_user_id: discordSnowflake('700000000000000003'), username: 'owner', global_name: null }, active_guild_id: guildId, csrf_token: 'csrf', policy_version: 1 },
    guild,
    guilds: [guild],
    connection: 'live',
    capabilities: capabilities(can),
  }} />
}

async function renderDecision(decision: CapabilityDecision | Error | 'pending') {
  apiRequestMock.mockReset()
  if (decision === 'pending') apiRequestMock.mockReturnValue(new Promise(() => undefined))
  else if (decision instanceof Error) apiRequestMock.mockRejectedValue(decision)
  else apiRequestMock.mockResolvedValue(capabilities(decision))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<BunnyTestProvider><QueryClientProvider client={client}><MemoryRouter initialEntries={[`/guild/${guildId}/roles`]}><Routes><Route path="/guild/:guildId" element={<Harness/>}><Route path="roles" element={<RolesScreen/>}/></Route></Routes></MemoryRouter></QueryClientProvider></BunnyTestProvider>)
  await userEvent.click(screen.getByRole('option', { name: /bots/i }))
}

describe('role bot capability presentation', () => {
  it('renders loading without calling it a business UNKNOWN', async () => {
    await renderDecision('pending')
    expect(screen.getByText('Bunny is checking this role')).toBeVisible()
    expect(screen.queryByText('Bot capability is unknown')).not.toBeInTheDocument()
  })

  it('renders CAN and enables compatible actions', async () => {
    await renderDecision(can)
    expect(await screen.findByRole('button', { name: 'Rename role' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Rename role' })).toBeEnabled()
  })

  it('renders CANNOT with the exact cause and remediation', async () => {
    await renderDecision({ outcome: 'CANNOT', causes: ['capability.permission_missing.manage_roles'], remediations: ['capability.remediation.grant.manage_roles'] })
    expect(await screen.findByText('This role is protected')).toBeVisible()
    expect(screen.getByText('The bot does not have the Manage Roles permission.')).toBeVisible()
    expect(screen.getByText('Grant the bot the Manage Roles permission.')).toBeVisible()
  })

  it('renders a hierarchy CANNOT with the target role in its remediation', async () => {
    await renderDecision({ outcome: 'CANNOT', causes: ['capability.hierarchy.bot_role_not_above_target'], remediations: ['capability.remediation.move_bot_role_above_target'] })
    expect(await screen.findByText('The bot’s highest role is not strictly above “bots”.')).toBeVisible()
    expect(screen.getByText('Move the bot role above “bots”.')).toBeVisible()
  })

  it('renders a legitimate UNKNOWN with its synchronization reason', async () => {
    await renderDecision({ outcome: 'UNKNOWN', causes: ['capability.hierarchy.bot_roles_incomplete'], remediations: ['capability.remediation.refresh_discord_data'] })
    expect(await screen.findByText('A check is needed before editing')).toBeVisible()
    expect(screen.getByText('The hierarchy cannot be checked because the bot’s roles are not fully synchronized.')).toBeVisible()
    expect(screen.getByText('Refresh the Discord data, then retry.')).toBeVisible()
  })

  it('renders an HTTP error separately from business UNKNOWN and offers retry', async () => {
    await renderDecision(new Error('network down'))
    expect(await screen.findByText('The check could not be completed')).toBeVisible()
    expect(screen.getByText(/request error, not an unknown Discord capability/i)).toBeVisible()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeVisible()
    expect(screen.queryByText('Bot capability is unknown')).not.toBeInTheDocument()
  })
})
