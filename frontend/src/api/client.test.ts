import { delay, http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { QueryClient } from '@tanstack/react-query'
import { apiRequest } from './client'
import { leaveTenant, tenantSignal } from './tenantLifecycle'
import { discordSnowflake } from '../shared/discord-id'
import { queryKeys } from './queryKeys'
import { useSessionStore } from '../shared/state/session'

const server = setupServer(
  ...[401, 403, 404, 409, 422].map((status) => http.get(`http://localhost/status/${status}`, () => HttpResponse.json({
    error: { code: `E_${status}`, message_key: 'errors.generic', params: {}, request_id: `r-${status}` },
  }, { status }))),
  http.get('http://localhost/status/200', () => HttpResponse.json({ ok: true })),
)

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

describe('STAGE 07 typed API client', () => {
  it('preserves 200 and typed 401/403/404/409/422 error envelopes', async () => {
    await expect(apiRequest<{ ok: boolean }>('http://localhost/status/200')).resolves.toEqual({ ok: true })
    for (const status of [401, 403, 404, 409, 422]) {
      await expect(apiRequest(`http://localhost/status/${status}`)).rejects.toMatchObject({ status })
    }
  })

  it('clears the authenticated session on expiration', async () => {
    useSessionStore.getState().setMe({ authenticated: true, user: { discord_user_id: discordSnowflake('700000000000000003'), username: 'owner', global_name: null }, active_guild_id: null, csrf_token: 'csrf', policy_version: 1 })
    await expect(apiRequest('http://localhost/status/401')).rejects.toMatchObject({ status: 401 })
    expect(useSessionStore.getState().me).toBeNull()
  })

  it('reports an offline transport failure without inventing an API envelope', async () => {
    server.use(http.get('http://localhost/offline', () => HttpResponse.error()))
    await expect(apiRequest('http://localhost/offline')).rejects.toBeInstanceOf(TypeError)
  })

  it('aborts an in-flight tenant A response and preserves tenant B state', async () => {
    const user = discordSnowflake('700000000000000003'); const guildA = discordSnowflake('700000000000000001'); const guildB = discordSnowflake('700000000000000002'); const client = new QueryClient()
    server.use(http.get('http://localhost/tenant-a', async () => { await delay(200); return HttpResponse.json({ guild_id: guildA }) }))
    client.setQueryData(queryKeys.tenant(user, guildB, 'structure'), { guild_id: guildB })
    const pending = apiRequest('http://localhost/tenant-a', { signal: tenantSignal(guildA) })
    await leaveTenant(client, user, guildA)
    await expect(pending).rejects.toHaveProperty('name', 'AbortError')
    expect(client.getQueryData(queryKeys.tenant(user, guildB, 'structure'))).toEqual({ guild_id: guildB })
  })
})
