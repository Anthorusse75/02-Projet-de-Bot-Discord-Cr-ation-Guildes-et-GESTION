import { useTranslation } from 'react-i18next'
import { useLocale } from '../../localization/runtime'
import type { LocaleCode, MessageKey } from '../../localization/catalog'
import { LocaleFlag, Select } from '../../shared/components/ui'

const flagKeys: Record<LocaleCode, MessageKey> = { en: 'locale.flag.en', fr: 'locale.flag.fr', de: 'locale.flag.de', es: 'locale.flag.es' }
export function LanguageSelector() {
  const { t } = useTranslation(); const locale = useLocale()
  return <div className="locale-control"><LocaleFlag locale={locale.locale} labelKey={flagKeys[locale.locale]} /><Select labelKey="locale.label" value={locale.override ?? ''} onChange={(event) => void locale.setOverride(event.target.value ? event.target.value as LocaleCode : null)}><option value="">{t('locale.auto')}</option>{locale.activeLocales.map((code) => <option key={code} value={code}>{t(`locale.${code}` as MessageKey)}</option>)}</Select></div>
}

