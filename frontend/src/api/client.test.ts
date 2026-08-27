import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { apiRequest } from './client'

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

  it('reports an offline transport failure without inventing an API envelope', async () => {
    server.use(http.get('http://localhost/offline', () => HttpResponse.error()))
    await expect(apiRequest('http://localhost/offline')).rejects.toBeInstanceOf(TypeError)
  })
})
