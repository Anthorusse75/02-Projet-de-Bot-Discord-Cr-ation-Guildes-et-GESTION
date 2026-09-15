import type { Structure } from '../../api/types'

export type MatrixResourceKind = 'CATEGORY' | 'TEXT_CHANNEL' | 'VOICE_CHANNEL'
export type MatrixResource = { id: string; kind: MatrixResourceKind; label: string; categoryId: string | null }

function channelKind(type: number): 'TEXT_CHANNEL' | 'VOICE_CHANNEL' {
  return type === 2 || type === 13 ? 'VOICE_CHANNEL' : 'TEXT_CHANNEL'
}

/**
 * Matrix columns: categories and their channels, plus root channels. Threads are excluded to
 * keep the grid readable and bounded, matching the DSG/DID channel-type conventions already used
 * by `buildPolicyTargets`.
 */
export function buildMatrixResources(structure: Structure | undefined): MatrixResource[] {
  const values: MatrixResource[] = []
  for (const category of structure?.categories ?? []) {
    values.push({ id: category.id, kind: 'CATEGORY', label: category.name, categoryId: null })
    for (const channel of category.channels) {
      values.push({ id: channel.id, kind: channelKind(channel.type), label: channel.name, categoryId: category.id })
    }
  }
  for (const channel of structure?.root_channels ?? []) {
    values.push({ id: channel.id, kind: channelKind(channel.type), label: channel.name, categoryId: null })
  }
  return values
}
