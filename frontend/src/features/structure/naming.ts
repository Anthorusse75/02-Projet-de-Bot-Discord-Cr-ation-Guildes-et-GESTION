import type { ResourceType } from '../interaction/actions'

export type DiscordNameValidation = { valid: true; characterCount: number } | { valid: false; characterCount: number; reason: 'empty' | 'tooLong' }

export function discordCharacterCount(value: string): number {
  return Array.from(value).length
}

export function validateDiscordResourceName(value: string): DiscordNameValidation {
  const characterCount = discordCharacterCount(value)
  if (characterCount === 0) return { valid: false, characterCount, reason: 'empty' }
  if (characterCount > 100) return { valid: false, characterCount, reason: 'tooLong' }
  return { valid: true, characterCount }
}

export function nameSuggestions(originalName: string, resourceType: ResourceType): string[] {
  const candidates = resourceType === 'CATEGORY'
    ? [`📌 ${originalName}`, `— ${originalName} —`, `• ${originalName}`]
    : [`💬 ${originalName}`, `│ ${originalName}`, `${originalName} •`]
  return candidates.filter((candidate) => validateDiscordResourceName(candidate).valid)
}

export function prependEmoji(value: string, emoji: string): string {
  const candidate = value.startsWith(`${emoji} `) ? value : `${emoji} ${value}`
  return validateDiscordResourceName(candidate).valid ? candidate : value
}
