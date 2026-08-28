import { useTranslation } from 'react-i18next'
import { useLocale } from '../../localization/runtime'
import type { LocaleCode } from '../../localization/catalog'
import { LocaleFlag, Select } from '../../shared/components/ui'

export function LanguageSelector() {
  const { t } = useTranslation(); const locale = useLocale()
  const active = locale.activeLocales.find((item) => item.locale_code === locale.locale)
  return <div className="locale-control"><LocaleFlag locale={locale.locale} label={active?.display_name ?? locale.locale} /><Select labelKey="locale.label" value={locale.override ?? ''} onChange={(event) => void locale.setOverride(event.target.value ? event.target.value as LocaleCode : null)}><option value="">{t('locale.auto')}</option>{locale.activeLocales.map((item) => <option key={item.locale_code} value={item.locale_code}>{item.display_name}</option>)}</Select></div>
}
