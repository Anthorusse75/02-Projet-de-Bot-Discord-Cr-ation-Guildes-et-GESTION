import i18n from 'i18next'
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { I18nextProvider } from 'react-i18next'

import { apiRequest } from '../api/client'
import { bootstrapPacks, en, type LocaleCode, type MessageKey, type MessagePack } from './catalog'

export const CATALOG_VERSION = 'did-ui-v1'
const supported = Object.keys(bootstrapPacks) as LocaleCode[]
const htmlPattern = /<\/?[a-z][^>]*>|javascript:|on\w+\s*=/i
const interpolationPattern = /{{\s*([A-Za-z0-9_.-]+)\s*}}/g

export type LocaleChoice = LocaleCode | null

export function resolveLocale(
  languages: readonly string[],
  active: readonly string[] = supported,
): LocaleCode {
  const normalized = new Map(active.map((value) => [value.toLowerCase(), value]))
  for (const language of languages) {
    const exact = normalized.get(language.toLowerCase())
    if (exact && supported.includes(exact as LocaleCode)) return exact as LocaleCode
    const base = language.split('-')[0]?.toLowerCase()
    const match = base ? normalized.get(base) : undefined
    if (match && supported.includes(match as LocaleCode)) return match as LocaleCode
  }
  return 'en'
}

function params(value: string): string[] {
  return [...value.matchAll(interpolationPattern)].map((match) => match[1] ?? '').sort()
}

export function validatePack(payload: unknown): MessagePack {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) throw new Error('PACK_SCHEMA')
  const candidate = payload as Record<string, unknown>
  const required = Object.keys(en).sort()
  if (Object.keys(candidate).sort().join('\0') !== required.join('\0')) throw new Error('PACK_COVERAGE')
  for (const key of required as MessageKey[]) {
    const value = candidate[key]
    if (typeof value !== 'string' || value.length === 0 || value.length > 2_000) throw new Error('PACK_VALUE')
    if (htmlPattern.test(value)) throw new Error('PACK_HTML')
    if (params(value).join('\0') !== params(en[key]).join('\0')) throw new Error('PACK_PARAMS')
  }
  return candidate as MessagePack
}

void i18n.init({
  lng: 'en', fallbackLng: false, interpolation: { escapeValue: true },
  resources: Object.fromEntries(supported.map((locale) => [locale, { translation: bootstrapPacks[locale] }])),
  returnNull: false,
})

type LocaleContextValue = {
  locale: LocaleCode
  override: LocaleChoice
  setOverride: (value: LocaleChoice) => Promise<void>
  activeLocales: readonly LocaleCode[]
}

const LocaleContext = createContext<LocaleContextValue | null>(null)

async function runtimePack(locale: LocaleCode): Promise<MessagePack | null> {
  try {
    const response = await apiRequest<{ catalog_version: string; payload: unknown }>(
      `/api/v1/ui/locales/${locale}/catalog/${CATALOG_VERSION}`,
      { anonymous: true },
    )
    if (response.catalog_version !== CATALOG_VERSION) return null
    return validatePack(response.payload)
  } catch {
    return null
  }
}

export function LocalizationProvider({ children }: { children: ReactNode }) {
  const [override, setOverrideState] = useState<LocaleChoice>(() => {
    const stored = localStorage.getItem('did.uiLocaleOverride')
    return supported.includes(stored as LocaleCode) ? (stored as LocaleCode) : null
  })
  const browserLocale = () => resolveLocale(navigator.languages)
  const [locale, setLocale] = useState<LocaleCode>(() => override ?? browserLocale())
  const [browserGeneration, setBrowserGeneration] = useState(0)

  useEffect(() => {
    let active = true
    const wanted = override ?? browserLocale()
    async function activate() {
      const pack = (await runtimePack(wanted)) ?? bootstrapPacks[wanted]
      if (!active) return
      i18n.addResourceBundle(wanted, 'translation', validatePack(pack), true, true)
      await i18n.changeLanguage(wanted)
      if (active) {
        document.documentElement.lang = wanted
        setLocale(wanted)
      }
    }
    void activate()
    return () => { active = false }
  }, [override, browserGeneration])

  useEffect(() => {
    const changed = () => { if (override === null) setBrowserGeneration((value) => value + 1) }
    window.addEventListener('languagechange', changed)
    return () => window.removeEventListener('languagechange', changed)
  }, [override])

  async function setOverride(value: LocaleChoice) {
    if (value === null) localStorage.removeItem('did.uiLocaleOverride')
    else localStorage.setItem('did.uiLocaleOverride', value)
    setOverrideState(value)
    try {
      await apiRequest('/api/v1/me/preferences', {
        method: 'PATCH', body: { ui_locale_override_code: value, timezone: null },
      })
    } catch {
      // Pre-auth and offline changes remain a safe local bootstrap preference.
    }
  }

  const value = useMemo(() => ({ locale, override, setOverride, activeLocales: supported }), [locale, override])
  return <LocaleContext.Provider value={value}><I18nextProvider i18n={i18n}>{children}</I18nextProvider></LocaleContext.Provider>
}

export function useLocale(): LocaleContextValue {
  const value = useContext(LocaleContext)
  if (!value) throw new Error('LocaleProvider missing')
  return value
}
