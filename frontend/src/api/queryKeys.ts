import type { DiscordSnowflake } from '../shared/discord-id'

export const queryKeys = {
  me: ['did', 'identity'] as const,
  guilds: (userId: DiscordSnowflake) => ['did', userId, 'guilds'] as const,
  tenant: (userId: DiscordSnowflake, guildId: DiscordSnowflake, feature: string, ...detail: string[]) =>
    ['did', userId, guildId, feature, ...detail] as const,
  library: (userId: DiscordSnowflake) => ['did', userId, 'user-control-plane', 'library'] as const,
}
