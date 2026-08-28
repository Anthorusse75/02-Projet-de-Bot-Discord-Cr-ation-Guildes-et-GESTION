import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { discordSnowflake } from '../../shared/discord-id'
import { useInteractionStore } from '../../shared/state/interaction'
import { StructureScreen } from './StructureScreen'

const A = discordSnowflake('700000000000000001')
const category = { guild_id: A, id: discordSnowflake('700000000000000004'), type: 4, name: 'Operations', position: 0, parent_id: null, resource_kind: 'DISCORD_RESOURCE', observability: 'VISIBLE', freshness: 'FRESH', data_assertion: 'CURRENT_CONFIRMED', channels: [] }
const channel = { guild_id: A, id: discordSnowflake('700000000000000005'), type: 0, name: 'general', position: 0, parent_id: null, resource_kind: 'DISCORD_RESOURCE', observability: 'VISIBLE', freshness: 'FRESH', data_assertion: 'CURRENT_CONFIRMED', threads: [] }
const capability = { outcome: 'CAN' as const, causes: [], remediations: [] }

vi.mock('../../api/queries', () => ({
  useStructure: () => ({ data: { categories: [category], root_channels: [channel] }, isLoading: false, isError: false, refetch: vi.fn() }),
  useDashboardCapabilities: () => ({ data: { guild_id: A, source: 'AUTHORIZATION_AND_LOCAL_CACHE', discord_rest_calls: 0, user_capabilities: { 'structure.write': capability, 'plans.create': capability }, scoped_capabilities: { scope_kind: 'GUILD', scope_id: '*', capabilities: {} }, bot_operations: { REORDER_CHANNELS: capability, CREATE_CHANNEL: capability }, coverage: 'FULL', completeness: 'FULL', freshness: 'FRESH' } }),
}))

function Harness() {
  const guild = { guild_id: A, name: 'Alpha', owner: true, permissions: '8', installation_status: 'ACTIVE' }
  return <Outlet context={{ me: { authenticated: true, user: { discord_user_id: discordSnowflake('700000000000000003'), username: 'owner', global_name: null }, active_guild_id: A, csrf_token: 'csrf', policy_version: 1 }, guild, guilds: [guild], connection: 'live', capabilities: undefined }} />
}

describe('mounted STAGE 07 drag lifecycle', () => {
  beforeEach(() => useInteractionStore.getState().clearTenantState())
  it('opens a real move intent only after a valid mounted left drop', () => {
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={[`/guild/${A}/structure`]}><Routes><Route path="/guild/:guildId" element={<Harness/>}><Route path="structure" element={<StructureScreen/>}/></Route></Routes></MemoryRouter></QueryClientProvider>)
    const source = document.querySelector<HTMLElement>('[data-drop-name="general"]'); const target = document.querySelector<HTMLElement>('[data-drop-name="Operations"]'); if (!source || !target) throw new Error('mounted drag fixtures missing')
    Object.defineProperty(document, 'elementFromPoint', { configurable: true, value: vi.fn(() => target) })
    fireEvent.pointerDown(source, { pointerId: 1, button: 0, pointerType: 'mouse', clientX: 0, clientY: 0 })
    fireEvent.pointerMove(source, { pointerId: 1, clientX: 8, clientY: 0 })
    fireEvent.pointerUp(source, { pointerId: 1, clientX: 8, clientY: 0 })
    expect(screen.getByRole('dialog', { name: 'dialog.previewTitle' })).toBeVisible()
    expect(useInteractionStore.getState().previewIntent).toMatchObject({ actionId: 'move', destination: { id: category.id } })
  })

  it('clears pointer state on pointercancel and lost capture', () => {
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={[`/guild/${A}/structure`]}><Routes><Route path="/guild/:guildId" element={<Harness/>}><Route path="structure" element={<StructureScreen/>}/></Route></Routes></MemoryRouter></QueryClientProvider>)
    const source = document.querySelector<HTMLElement>('[data-drop-name="general"]'); if (!source) throw new Error('mounted drag source missing')
    fireEvent.pointerDown(source, { pointerId: 2, button: 0, pointerType: 'touch', clientX: 0, clientY: 0 }); fireEvent.pointerCancel(source, { pointerId: 2 })
    expect(useInteractionStore.getState().announcement).toBe('gesture.cancelled')
    fireEvent.pointerDown(source, { pointerId: 3, button: 0, pointerType: 'mouse', clientX: 0, clientY: 0 }); fireEvent.lostPointerCapture(source, { pointerId: 3 })
    expect(useInteractionStore.getState().previewIntent).toBeNull()
  })

  it('opens the mounted object menu for a right click', () => {
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={[`/guild/${A}/structure`]}><Routes><Route path="/guild/:guildId" element={<Harness/>}><Route path="structure" element={<StructureScreen/>}/></Route></Routes></MemoryRouter></QueryClientProvider>)
    const source = document.querySelector<HTMLElement>('[data-drop-name="general"]'); if (!source) throw new Error('mounted context source missing')
    fireEvent.pointerDown(source, { pointerId: 4, button: 2, pointerType: 'mouse', clientX: 2, clientY: 3 })
    fireEvent.pointerUp(source, { pointerId: 4, button: 2, pointerType: 'mouse', clientX: 2, clientY: 3 })
    expect(screen.getByRole('menu', { name: 'context.title' })).toBeVisible()
    expect(useInteractionStore.getState().context).toMatchObject({ kind: 'object', source: [{ id: channel.id }] })
  })

  it('opens the mounted drop menu for a right drag', () => {
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={[`/guild/${A}/structure`]}><Routes><Route path="/guild/:guildId" element={<Harness/>}><Route path="structure" element={<StructureScreen/>}/></Route></Routes></MemoryRouter></QueryClientProvider>)
    const source = document.querySelector<HTMLElement>('[data-drop-name="general"]'); const target = document.querySelector<HTMLElement>('[data-drop-name="Operations"]'); if (!source || !target) throw new Error('mounted right drag fixtures missing')
    Object.defineProperty(document, 'elementFromPoint', { configurable: true, value: vi.fn(() => target) })
    fireEvent.pointerDown(source, { pointerId: 5, button: 2, pointerType: 'mouse', clientX: 0, clientY: 0 })
    fireEvent.pointerMove(source, { pointerId: 5, button: 2, clientX: 12, clientY: 0 })
    fireEvent.pointerUp(source, { pointerId: 5, button: 2, clientX: 12, clientY: 0 })
    expect(screen.getByRole('menu', { name: 'context.dropTitle' })).toBeVisible()
    expect(useInteractionStore.getState().context).toMatchObject({ kind: 'drop', destination: { id: category.id } })
  })
})
