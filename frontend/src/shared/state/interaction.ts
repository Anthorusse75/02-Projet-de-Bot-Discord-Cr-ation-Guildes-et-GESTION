import { create } from 'zustand'
import type { DiscordSnowflake } from '../discord-id'
import type { ActionContext, ResourceRef } from '../../features/interaction/actions'

type Point = { x: number; y: number }
type InteractionStore = {
  selection: ResourceRef[]
  context: (ActionContext & Point & { kind: 'object' | 'drop' }) | null
  previewActionId: string | null
  commandOpen: boolean
  announcement: string
  setSelection: (value: ResourceRef[]) => void
  setContext: (value: InteractionStore['context']) => void
  setPreview: (actionId: string | null) => void
  setCommandOpen: (value: boolean) => void
  announce: (value: string) => void
  clearTenantState: () => void
}

export const useInteractionStore = create<InteractionStore>((set) => ({
  selection: [], context: null, previewActionId: null, commandOpen: false, announcement: '',
  setSelection: (selection) => set({ selection }), setContext: (context) => set({ context }),
  setPreview: (previewActionId) => set({ previewActionId }), setCommandOpen: (commandOpen) => set({ commandOpen }),
  announce: (announcement) => set({ announcement }),
  clearTenantState: () => set({ selection: [], context: null, previewActionId: null, commandOpen: false, announcement: '' }),
}))

export type TenantIdentity = { userId: DiscordSnowflake; guildId: DiscordSnowflake }

