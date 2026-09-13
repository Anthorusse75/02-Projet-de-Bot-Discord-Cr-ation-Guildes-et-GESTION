import { lazy, Suspense, useState, type KeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'
import type { PickerProps } from 'emoji-picker-react'
import type { ResourceType } from '../interaction/actions'
import { nameSuggestions, prependEmoji, validateDiscordResourceName } from './naming'

const EmojiPicker = lazy(() => import('emoji-picker-react'))
const nativeEmojiStyle = 'native' as NonNullable<PickerProps['emojiStyle']>
const darkTheme = 'dark' as NonNullable<PickerProps['theme']>

type NameEditorProps = {
  originalName: string
  resourceType: ResourceType
  value: string
  busy: boolean
  onChange: (value: string) => void
  onSubmit: () => void
  onCancel: () => void
}

export function NameEditor({ originalName, resourceType, value, busy, onChange, onSubmit, onCancel }: NameEditorProps) {
  const { t } = useTranslation()
  const [pickerOpen, setPickerOpen] = useState(false)
  const validation = validateDiscordResourceName(value)
  const errorKey = validation.valid ? null : validation.reason === 'empty' ? 'structure.naming.empty' : 'structure.naming.tooLong'

  function keyboard(event: KeyboardEvent<HTMLInputElement>) {
    event.stopPropagation()
    if (event.key === 'Escape') { event.preventDefault(); onCancel() }
    if (event.key === 'Enter' && validation.valid && !busy) { event.preventDefault(); onSubmit() }
  }

  return (
    <div className="structure-name-editor" onClick={(event) => event.stopPropagation()} onPointerDown={(event) => event.stopPropagation()}>
      <div className="structure-name-input-row">
        <input
          autoFocus
          aria-label={t('structure.naming.field')}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={keyboard}
          aria-invalid={!validation.valid}
          aria-describedby={errorKey ? 'structure-name-error' : undefined}
        />
        <button type="button" className="name-tool-button" aria-label={t('structure.naming.emoji')} aria-expanded={pickerOpen} onClick={() => setPickerOpen((open) => !open)}>☺</button>
        <button type="button" className="name-tool-button confirm" aria-label={t('structure.naming.confirm')} disabled={!validation.valid || busy} onClick={onSubmit}>✓</button>
        <button type="button" className="name-tool-button" aria-label={t('structure.naming.cancel')} onClick={onCancel}>×</button>
      </div>
      <div className="structure-name-meta">
        <span>{t('structure.naming.count', { count: validation.characterCount })}</span>
        {errorKey && <span id="structure-name-error" role="alert">{t(errorKey)}</span>}
      </div>
      <div className="structure-name-suggestions" aria-label={t('structure.naming.suggestions')}>
        {nameSuggestions(originalName, resourceType).map((suggestion) => <button type="button" key={suggestion} onClick={() => onChange(suggestion)}>{suggestion}</button>)}
        {value !== originalName && <button type="button" onClick={() => onChange(originalName)}>{t('structure.naming.reset')}</button>}
      </div>
      <div className="structure-name-preview"><small>{t('structure.naming.preview')}</small><strong>{value || '—'}</strong></div>
      {pickerOpen && (
        <div className="structure-emoji-picker" aria-label={t('structure.naming.emoji')}>
          <Suspense fallback={<span>{t('common.loading')}</span>}>
            <EmojiPicker
              theme={darkTheme}
              emojiStyle={nativeEmojiStyle}
              width={310}
              height={360}
              previewConfig={{ showPreview: false }}
              onEmojiClick={(emoji) => { onChange(prependEmoji(value, emoji.emoji)); setPickerOpen(false) }}
            />
          </Suspense>
        </div>
      )}
    </div>
  )
}
