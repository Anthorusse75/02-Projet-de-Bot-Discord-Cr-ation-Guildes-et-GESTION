import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import { App } from './App'

describe('STAGE 02 session shell', () => {
  it('renders the anonymous login state', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input)
      if (path.includes('/api/v1/ui/locales/')) return new Response('', { status: 404 })
      return new Response(JSON.stringify({ error: { code: 'AUTH_REQUIRED', message_key: 'errors.auth.required', params: {}, request_id: 'test' } }), {
        status: 401, headers: { 'Content-Type': 'application/json' },
      })
    }))
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    )
    expect(await screen.findByRole('heading', { name: 'Discord Infrastructure Designer' })).toBeVisible()
    expect(screen.getByRole('link', { name: 'Continue with Discord' })).toHaveAttribute(
      'href',
      '/auth/discord/login',
    )
  })

  it('renders authenticated guilds with snowflakes kept as strings', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input)
      if (path.includes('/api/v1/ui/locales/')) return new Response('', { status: 404 })
      if (path === '/api/v1/me') return Response.json({
          authenticated: true,
          user: { discord_user_id: '9007199254740993', username: 'owner', global_name: null },
          active_guild_id: null,
          csrf_token: 'csrf',
          policy_version: 1,
        })
      if (path === '/api/v1/guilds') return Response.json({
          guilds: [
            {
              guild_id: '9007199254740995',
              name: 'Guild A',
              owner: true,
              permissions: '8',
              installation_status: 'PENDING_SETUP',
            },
          ],
        })
      return new Response('', { status: 404 })
    })
    vi.stubGlobal('fetch', fetchMock)
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    )
    expect(await screen.findByText('Guild A')).toBeVisible()
    expect(screen.getByText('Setup required')).toBeVisible()
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/v1/guilds', expect.anything()))
  })
})
