import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import { App } from './App'

describe('STAGE 02 session shell', () => {
  it('renders the anonymous login state', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ status: 401, ok: false }))
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    )
    expect(screen.getByRole('heading', { name: 'Discord Infrastructure Designer' })).toBeVisible()
    expect(await screen.findByRole('link', { name: 'Continue with Discord' })).toHaveAttribute(
      'href',
      '/auth/discord/login',
    )
  })

  it('renders authenticated guilds with snowflakes kept as strings', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        status: 200,
        ok: true,
        json: async () => ({
          authenticated: true,
          user: { discord_user_id: '9007199254740993', username: 'owner', global_name: null },
          active_guild_id: null,
          csrf_token: 'csrf',
          policy_version: 1,
        }),
      })
      .mockResolvedValueOnce({
        status: 200,
        ok: true,
        json: async () => ({
          guilds: [
            {
              guild_id: '9007199254740995',
              name: 'Guild A',
              owner: true,
              permissions: '8',
              installation_status: 'PENDING_SETUP',
            },
          ],
        }),
      })
    vi.stubGlobal('fetch', fetchMock)
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    )
    expect(await screen.findByText('Guild A')).toBeVisible()
    expect(screen.getByText('Setup required')).toBeVisible()
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
  })
})
