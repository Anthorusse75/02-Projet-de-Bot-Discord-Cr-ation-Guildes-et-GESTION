import { MantineProvider } from '@mantine/core'
import { ModalsProvider } from '@mantine/modals'
import { Notifications } from '@mantine/notifications'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { LocalizationProvider } from '../../localization/runtime'
import { GlobalContextMenuBoundary } from '../../features/interaction/GlobalContextMenuBoundary'
import { bunnyTheme } from '../theme'

export function AppProviders({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { staleTime: 15_000, retry: 1, refetchOnWindowFocus: false } } }))
  return (
    <QueryClientProvider client={client}>
      <LocalizationProvider>
        <MantineProvider theme={bunnyTheme} defaultColorScheme="light">
          <ModalsProvider>
            <Notifications position="top-right" limit={4} />
            <GlobalContextMenuBoundary>{children}</GlobalContextMenuBoundary>
          </ModalsProvider>
        </MantineProvider>
      </LocalizationProvider>
    </QueryClientProvider>
  )
}
