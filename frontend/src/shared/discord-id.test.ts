import { discordSnowflake } from './discord-id'

describe('Discord snowflake API boundary', () => {
  it('keeps identifiers as strings', () => {
    expect(discordSnowflake('123456789012345678')).toBe('123456789012345678')
  })

  it('rejects unsafe values', () => {
    expect(() => discordSnowflake('1.23')).toThrow('Invalid Discord snowflake string')
  })
})
