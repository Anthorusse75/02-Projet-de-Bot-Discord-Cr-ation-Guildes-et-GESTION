import type { ApiErrorEnvelope } from './types'
import { useSessionStore } from '../shared/state/session'

export class ApiError extends Error {
  constructor(public readonly status: number, public readonly problem: ApiErrorEnvelope['error']) {
    super(problem.code)
  }
}

type RequestOptions = Omit<RequestInit, 'body'> & { body?: unknown; anonymous?: boolean }

export async function apiRequest<T = unknown>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, anonymous, headers, ...init } = options
  void anonymous
  const session = useSessionStore.getState().me
  const mutation = Boolean(init.method && !['GET', 'HEAD'].includes(init.method))
  const requestHeaders = new Headers(headers)
  if (body !== undefined) requestHeaders.set('Content-Type', 'application/json')
  if (mutation && session) requestHeaders.set('X-CSRF-Token', session.csrf_token)
  const requestInit: RequestInit = {
    ...init,
    credentials: 'include',
    headers: requestHeaders,
  }
  if (body !== undefined) requestInit.body = JSON.stringify(body)
  const response = await fetch(path, requestInit)
  if (response.status === 401) useSessionStore.getState().setMe(null)
  if (!response.ok) {
    let problem: ApiErrorEnvelope['error'] = { code: `HTTP_${response.status}`, message_key: 'errors.generic', params: {}, request_id: response.headers.get('X-Correlation-ID') ?? 'unknown' }
    try { problem = ((await response.json()) as ApiErrorEnvelope).error ?? problem } catch { /* typed fallback */ }
    throw new ApiError(response.status, problem)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}
