import { useTranslation } from 'react-i18next'
import { useLocale } from '../../localization/runtime'
import type { LocaleCode } from '../../localization/catalog'

export function LanguageSelector() {
  const { t } = useTranslation()
  const locale = useLocale()
  const active = locale.activeLocales.find((item) => item.locale_code === locale.locale)
  const code = locale.locale.split('-')[0]?.toUpperCase() ?? locale.locale.toUpperCase()

  return (
    <label className="locale-control" aria-label={t('locale.label')}>
      <span className="locale-code" aria-hidden="true">{code}</span>
      <select
        value={locale.override ?? ''}
        aria-label={t('locale.label')}
        title={active?.display_name ?? locale.locale}
        onChange={(event) => void locale.setOverride(event.target.value ? event.target.value as LocaleCode : null)}
      >
        <option value="">{t('locale.auto')}</option>
        {locale.activeLocales.map((item) => <option key={item.locale_code} value={item.locale_code}>{item.display_name}</option>)}
      </select>
    </label>
  )
}
