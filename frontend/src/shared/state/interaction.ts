import { create } from 'zustand'
import type { DiscordSnowflake } from '../discord-id'
import type { ActionContext, ResourceRef } from '../../features/interaction/actions'
import type { ActionIntent } from '../../features/interaction/dispatcher'

type Point = { x: number; y: number }
type InteractionStore = {
  selection: ResourceRef[]
  context: (ActionContext & Point & { kind: 'object' | 'drop' }) | null
  previewIntent: ActionIntent | null
  commandOpen: boolean
  announcement: string
  setSelection: (value: ResourceRef[]) => void
  setContext: (value: InteractionStore['context']) => void
  setPreview: (intent: ActionIntent | null) => void
  setCommandOpen: (value: boolean) => void
  announce: (value: string) => void
  clearTenantState: () => void
}

export const useInteractionStore = create<InteractionStore>((set) => ({
  selection: [], context: null, previewIntent: null, commandOpen: false, announcement: '',
  setSelection: (selection) => set({ selection }), setContext: (context) => set({ context }),
  setPreview: (previewIntent) => set({ previewIntent }), setCommandOpen: (commandOpen) => set({ commandOpen }),
  announce: (announcement) => set({ announcement }),
  clearTenantState: () => set({ selection: [], context: null, previewIntent: null, commandOpen: false, announcement: '' }),
}))

export type TenantIdentity = { userId: DiscordSnowflake; guildId: DiscordSnowflake }
