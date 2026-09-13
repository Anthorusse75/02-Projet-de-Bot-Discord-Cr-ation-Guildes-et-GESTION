import { describe, expect, it } from 'vitest'
import { discordCharacterCount, nameSuggestions, prependEmoji, validateDiscordResourceName } from './naming'

describe('Discord structure naming', () => {
  it('counts Unicode code points and accepts an emoji name within Discord 1-100 bounds', () => {
    expect(discordCharacterCount('📌 accueil')).toBe(9)
    expect(validateDiscordResourceName('📌 accueil')).toEqual({ valid: true, characterCount: 9 })
  })

  it('rejects empty and over-100-character names before plan creation', () => {
    expect(validateDiscordResourceName('')).toMatchObject({ valid: false, reason: 'empty' })
    expect(validateDiscordResourceName('a'.repeat(101))).toMatchObject({ valid: false, reason: 'tooLong' })
  })

  it('only returns valid, optional suggestions and never mutates the source value', () => {
    const source = 'annonces'
    expect(nameSuggestions(source, 'CHANNEL').every((name) => validateDiscordResourceName(name).valid)).toBe(true)
    expect(source).toBe('annonces')
    expect(prependEmoji(source, '📣')).toBe('📣 annonces')
  })
})
