import { create } from 'zustand'
import type { Me } from '../../api/types'

type SessionStore = {
  me: Me | null
  setMe: (me: Me | null) => void
}

export const useSessionStore = create<SessionStore>((set) => ({ me: null, setMe: (me) => set({ me }) }))

