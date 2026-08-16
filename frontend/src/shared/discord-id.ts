declare const discordSnowflakeBrand: unique symbol

export type DiscordSnowflake = string & { readonly [discordSnowflakeBrand]: true }

export function discordSnowflake(value: string): DiscordSnowflake {
  if (!/^[1-9][0-9]{0,19}$/.test(value)) {
    throw new Error('Invalid Discord snowflake string')
  }
  return value as DiscordSnowflake
}
