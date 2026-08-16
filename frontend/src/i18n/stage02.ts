const messages = {
  'app.title': 'Discord Infrastructure Designer',
  'auth.loading': 'Checking your session…',
  'auth.login': 'Continue with Discord',
  'auth.logout': 'Sign out',
  'auth.error': 'Authentication is unavailable. Please try again.',
  'guilds.title': 'Choose a server',
  'guilds.empty': 'No eligible Discord server was found.',
  'guilds.select': 'Open server',
  'guilds.pending': 'Setup required',
  'guilds.active': 'Active',
} as const

export type Stage02MessageKey = keyof typeof messages

export function t(key: Stage02MessageKey): string {
  return messages[key]
}
