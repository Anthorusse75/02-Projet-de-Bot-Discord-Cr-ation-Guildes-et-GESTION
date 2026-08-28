import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { LocalizationProvider } from '../../localization/runtime'
import { GlobalContextMenuBoundary } from '../../features/interaction/GlobalContextMenuBoundary'

export function AppProviders({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { staleTime: 15_000, retry: 1, refetchOnWindowFocus: false } } }))
  return <QueryClientProvider client={client}><LocalizationProvider><GlobalContextMenuBoundary>{children}</GlobalContextMenuBoundary></LocalizationProvider></QueryClientProvider>
}
