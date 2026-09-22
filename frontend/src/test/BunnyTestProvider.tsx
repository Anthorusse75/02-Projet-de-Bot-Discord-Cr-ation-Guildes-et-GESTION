import { MantineProvider } from '@mantine/core'
import type { PropsWithChildren } from 'react'
import { bunnyTheme } from '../app/theme'

export function BunnyTestProvider({ children }: PropsWithChildren) {
  return (
    <MantineProvider theme={bunnyTheme} defaultColorScheme="light" env="test">
      {children}
    </MantineProvider>
  )
}
