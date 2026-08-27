import { bootstrapPacks, en, type MessageKey } from './catalog'
import { resolveLocale, validatePack } from './runtime'

const params = (value: string) => [...value.matchAll(/{{\s*([A-Za-z0-9_.-]+)\s*}}/g)].map((match) => match[1]).sort()

describe('STAGE 07 locale catalogue', () => {
  it('ships exact, safe and interpolation-compatible packs', () => {
    const keys = Object.keys(en).sort()
    for (const pack of Object.values(bootstrapPacks)) {
      expect(Object.keys(pack).sort()).toEqual(keys)
      expect(validatePack(pack)).toEqual(pack)
      for (const key of keys as MessageKey[]) {
        expect(pack[key]).not.toMatch(/<\/?[a-z]|javascript:|on\w+\s*=/i)
        expect(params(pack[key])).toEqual(params(en[key]))
      }
    }
  })

  it('resolves BCP-47 preferences and falls back deterministically', () => {
    expect(resolveLocale(['fr-CA', 'en-US'])).toBe('fr')
    expect(resolveLocale(['de-DE'])).toBe('de')
    expect(resolveLocale(['pt-BR'])).toBe('en')
    expect(resolveLocale(['fr'], ['en', 'de'])).toBe('en')
  })

  it('rejects partial, executable and parameter-incompatible runtime packs atomically', () => {
    expect(() => validatePack({ ...en, 'app.title': '<script>alert(1)</script>' })).toThrow('PACK_HTML')
    expect(() => validatePack({ ...en, 'common.selectedCount': 'Selected' })).toThrow('PACK_PARAMS')
    const partial: Record<string, string> = { ...en }
    delete partial['app.title']
    expect(() => validatePack(partial)).toThrow('PACK_COVERAGE')
  })
})
