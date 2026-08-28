import i18n from 'i18next'
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { I18nextProvider } from 'react-i18next'
import { apiRequest } from '../api/client'
import { bootstrapPacks, en, type BootstrapLocaleCode, type LocaleCode, type MessageKey, type MessagePack } from './catalog'

export const CATALOG_VERSION = 'did-ui-v1'
const bootstrap = Object.keys(bootstrapPacks) as BootstrapLocaleCode[]
const htmlPattern = /<\/?[a-z][^>]*>|javascript:|on\w+\s*=/i
const interpolationPattern = /{{\s*([A-Za-z0-9_.-]+)\s*}}/g
const localePattern = /^[a-z]{2,3}(?:-[A-Z]{2})?$/
export type LocaleChoice = LocaleCode | null
export type ActiveLocale = { locale_code: LocaleCode; display_name: string; flag_code: string; direction: 'ltr'|'rtl' }
const bootstrapMetadata: ActiveLocale[] = [
  { locale_code: 'en', display_name: 'English', flag_code: 'gb', direction: 'ltr' }, { locale_code: 'fr', display_name: 'Français', flag_code: 'fr', direction: 'ltr' },
  { locale_code: 'de', display_name: 'Deutsch', flag_code: 'de', direction: 'ltr' }, { locale_code: 'es', display_name: 'Español', flag_code: 'es', direction: 'ltr' },
]

export function resolveLocale(languages: readonly string[], active: readonly string[] = bootstrap): LocaleCode {
  const normalized = new Map(active.map((value) => [value.toLowerCase(), value]))
  for (const language of languages) { const exact = normalized.get(language.toLowerCase()); if (exact) return exact; const base = language.split('-')[0]?.toLowerCase(); const match = base ? normalized.get(base) : undefined; if (match) return match }
  return active.includes('en') ? 'en' : active[0] ?? 'en'
}
function params(value: string): string[] { return [...value.matchAll(interpolationPattern)].map((match) => match[1] ?? '').sort() }
export function validatePack(payload: unknown): MessagePack { if (!payload || typeof payload !== 'object' || Array.isArray(payload)) throw new Error('PACK_SCHEMA'); const candidate = payload as Record<string, unknown>; const required = Object.keys(en).sort(); if (Object.keys(candidate).sort().join('\0') !== required.join('\0')) throw new Error('PACK_COVERAGE'); for (const key of required as MessageKey[]) { const value = candidate[key]; if (typeof value !== 'string' || value.length === 0 || value.length > 2_000) throw new Error('PACK_VALUE'); if (htmlPattern.test(value)) throw new Error('PACK_HTML'); if (params(value).join('\0') !== params(en[key]).join('\0')) throw new Error('PACK_PARAMS') } return candidate as MessagePack }
void i18n.init({ lng: 'en', fallbackLng: false, interpolation: { escapeValue: true }, resources: Object.fromEntries(bootstrap.map((locale) => [locale, { translation: bootstrapPacks[locale] }])), returnNull: false })

type LocaleContextValue = { locale: LocaleCode; override: LocaleChoice; setOverride: (value: LocaleChoice) => Promise<void>; hydrateServerPreference: (value: LocaleChoice) => void; activeLocales: readonly ActiveLocale[] }
const LocaleContext = createContext<LocaleContextValue | null>(null)
async function runtimePack(locale: LocaleCode): Promise<MessagePack | null> { try { const response = await apiRequest<{ catalog_version: string; payload: unknown }>(`/api/v1/ui/locales/${locale}/catalog/${CATALOG_VERSION}`, { anonymous: true }); if (response.catalog_version !== CATALOG_VERSION) return null; return validatePack(response.payload) } catch { return null } }
function bundledPack(locale: string): MessagePack | undefined { return bootstrap.includes(locale as BootstrapLocaleCode) ? bootstrapPacks[locale as BootstrapLocaleCode] : undefined }

export function LocalizationProvider({ children }: { children: ReactNode }) {
  const [activeLocales, setActiveLocales] = useState<ActiveLocale[]>(bootstrapMetadata); const activeCodes = activeLocales.map((item) => item.locale_code)
  const [override, setOverrideState] = useState<LocaleChoice>(() => { const stored = localStorage.getItem('did.uiLocaleOverride'); return stored && localePattern.test(stored) ? stored : null })
  const browserLocale = () => resolveLocale(navigator.languages, activeCodes); const [locale, setLocale] = useState<LocaleCode>(() => override ?? browserLocale()); const [browserGeneration, setBrowserGeneration] = useState(0)
  useEffect(() => { let current = true; void apiRequest<{locales: ActiveLocale[]}>('/api/v1/ui/locales', { anonymous: true }).then((response) => { const valid = response.locales.filter((item) => localePattern.test(item.locale_code) && item.display_name && ['ltr','rtl'].includes(item.direction)); if (current && valid.length) setActiveLocales(valid) }).catch(() => undefined); return () => { current = false } }, [])
  useEffect(() => { let current = true; const wanted = override !== null && activeCodes.includes(override) ? override : browserLocale(); async function activate() { const pack = bundledPack(wanted) ?? await runtimePack(wanted); if (!current || !pack) return; i18n.addResourceBundle(wanted, 'translation', validatePack(pack), true, true); await i18n.changeLanguage(wanted); if (current) { document.documentElement.lang = wanted; document.documentElement.dir = activeLocales.find((item) => item.locale_code === wanted)?.direction ?? 'ltr'; setLocale(wanted) } } void activate(); return () => { current = false } }, [activeCodes.join('\0'), browserGeneration, override])
  useEffect(() => { const changed = () => { if (override === null) setBrowserGeneration((value) => value + 1) }; window.addEventListener('languagechange', changed); return () => window.removeEventListener('languagechange', changed) }, [override])
  function hydrateServerPreference(value: LocaleChoice) { if (value === null || localePattern.test(value)) { if (value === null) localStorage.removeItem('did.uiLocaleOverride'); else localStorage.setItem('did.uiLocaleOverride', value); setOverrideState(value) } }
  async function setOverride(value: LocaleChoice) { hydrateServerPreference(value); try { await apiRequest('/api/v1/me/preferences', { method: 'PATCH', body: { ui_locale_override_code: value, timezone: null } }) } catch { /* The local choice remains usable while offline. */ } }
  const value = useMemo(() => ({ locale, override, setOverride, hydrateServerPreference, activeLocales }), [activeLocales, locale, override]); return <LocaleContext.Provider value={value}><I18nextProvider i18n={i18n}>{children}</I18nextProvider></LocaleContext.Provider>
}
export function useLocale(): LocaleContextValue { const value = useContext(LocaleContext); if (!value) throw new Error('LocaleProvider missing'); return value }
