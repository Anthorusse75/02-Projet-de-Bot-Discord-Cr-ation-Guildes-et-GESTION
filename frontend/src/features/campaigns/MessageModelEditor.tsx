import { useTranslation } from 'react-i18next'
import type { ButtonStyle, ComponentActionRow, ComponentButton, Embed, EmbedField } from '../../api/types'
import type { MessageKey } from '../../localization/catalog'
import { Button, Input, Select } from '../../shared/components/ui'

const buttonStyleKeys: Record<ButtonStyle, MessageKey> = {
  PRIMARY: 'campaigns.messageModel.buttonStyle.primary',
  SECONDARY: 'campaigns.messageModel.buttonStyle.secondary',
  SUCCESS: 'campaigns.messageModel.buttonStyle.success',
  DANGER: 'campaigns.messageModel.buttonStyle.danger',
  LINK: 'campaigns.messageModel.buttonStyle.link',
}

// Mirrors did.messaging.message_model.DiscordLimits exactly -- the backend
// is the authoritative validator (validate_message_model, enforced on
// every create/update/owned-edit), these are only for a helpful client-side
// cap, never a substitute for the server-side check.
export const MESSAGE_MODEL_LIMITS = {
  maxEmbeds: 10,
  maxEmbedTitle: 256,
  maxEmbedDescription: 4096,
  maxEmbedFooter: 2048,
  maxEmbedAuthorName: 256,
  maxEmbedFields: 25,
  maxEmbedFieldName: 256,
  maxEmbedFieldValue: 1024,
  maxActionRows: 5,
  maxButtonsPerRow: 5,
} as const

const buttonStyles: readonly ButtonStyle[] = ['PRIMARY', 'SECONDARY', 'SUCCESS', 'DANGER', 'LINK']

export function emptyEmbed(): Embed {
  return { title: '', description: '', url: '', color: null, footer_text: '', author_name: '', fields: [] }
}

export function emptyButton(): ComponentButton {
  return { label: '', style: 'PRIMARY', custom_id: '', url: null }
}

interface MessageModelEditorProps {
  idPrefix: string
  embeds: Embed[]
  actionRows: ComponentActionRow[]
  onEmbedsChange: (embeds: Embed[]) => void
  onActionRowsChange: (rows: ComponentActionRow[]) => void
}

/** REQ-MSG mission section 9: full embed/component authoring for the
 * campaign MessageModel, against the real backend schema
 * (did.messaging.message_model) -- not a second, parallel frontend model.
 * Technical fields (embed url/color, button custom_id/url) are plain
 * inputs here, same as every other field: this form edits the SOURCE
 * content only, and REQ-MSG-013's translation policy (did.messaging
 * .translation_policy) is what keeps these specific fields untouched by
 * the separate, automatic per-language translation pipeline -- there is
 * nothing for this authoring form itself to protect. */
export function MessageModelEditor({ idPrefix, embeds, actionRows, onEmbedsChange, onActionRowsChange }: MessageModelEditorProps) {
  const { t } = useTranslation()

  function updateEmbed(index: number, patch: Partial<Embed>) {
    onEmbedsChange(embeds.map((embed, i) => (i === index ? { ...embed, ...patch } : embed)))
  }
  function addEmbed() {
    if (embeds.length >= MESSAGE_MODEL_LIMITS.maxEmbeds) return
    onEmbedsChange([...embeds, emptyEmbed()])
  }
  function removeEmbed(index: number) {
    onEmbedsChange(embeds.filter((_, i) => i !== index))
  }
  function addField(embedIndex: number) {
    const embed = embeds[embedIndex]
    if (!embed || embed.fields.length >= MESSAGE_MODEL_LIMITS.maxEmbedFields) return
    updateEmbed(embedIndex, { fields: [...embed.fields, { name: '', value: '', inline: false }] })
  }
  function updateField(embedIndex: number, fieldIndex: number, patch: Partial<EmbedField>) {
    const embed = embeds[embedIndex]
    if (!embed) return
    updateEmbed(embedIndex, { fields: embed.fields.map((f, i) => (i === fieldIndex ? { ...f, ...patch } : f)) })
  }
  function removeField(embedIndex: number, fieldIndex: number) {
    const embed = embeds[embedIndex]
    if (!embed) return
    updateEmbed(embedIndex, { fields: embed.fields.filter((_, i) => i !== fieldIndex) })
  }

  function addRow() {
    if (actionRows.length >= MESSAGE_MODEL_LIMITS.maxActionRows) return
    onActionRowsChange([...actionRows, { buttons: [] }])
  }
  function removeRow(rowIndex: number) {
    onActionRowsChange(actionRows.filter((_, i) => i !== rowIndex))
  }
  function addButton(rowIndex: number) {
    const row = actionRows[rowIndex]
    if (!row || row.buttons.length >= MESSAGE_MODEL_LIMITS.maxButtonsPerRow) return
    onActionRowsChange(actionRows.map((r, i) => (i === rowIndex ? { buttons: [...r.buttons, emptyButton()] } : r)))
  }
  function updateButton(rowIndex: number, buttonIndex: number, patch: Partial<ComponentButton>) {
    onActionRowsChange(actionRows.map((r, i) =>
      i === rowIndex ? { buttons: r.buttons.map((b, j) => (j === buttonIndex ? { ...b, ...patch } : b)) } : r))
  }
  function removeButton(rowIndex: number, buttonIndex: number) {
    onActionRowsChange(actionRows.map((r, i) => (i === rowIndex ? { buttons: r.buttons.filter((_, j) => j !== buttonIndex) } : r)))
  }
  function setButtonStyle(rowIndex: number, buttonIndex: number, style: ButtonStyle) {
    // LINK carries a url, never a custom_id; every other style carries a
    // custom_id, never a url -- matches validate_message_model exactly, so
    // switching styles never leaves a stale, now-invalid combination.
    updateButton(rowIndex, buttonIndex, style === 'LINK' ? { style, custom_id: '', url: '' } : { style, url: null, custom_id: '' })
  }

  return <div className="message-model-editor">
    <section className="message-model-embeds">
      <h4>{t('campaigns.messageModel.embeds')}</h4>
      {embeds.map((embed, embedIndex) => <div className="message-model-embed" key={embedIndex}>
        <Input labelKey="campaigns.messageModel.embedTitle" id={`${idPrefix}-embed-${embedIndex}-title`} value={embed.title ?? ''} maxLength={MESSAGE_MODEL_LIMITS.maxEmbedTitle} onChange={(event) => updateEmbed(embedIndex, { title: event.target.value })} />
        <label className="field" htmlFor={`${idPrefix}-embed-${embedIndex}-description`}><span>{t('campaigns.messageModel.embedDescription')}</span><textarea id={`${idPrefix}-embed-${embedIndex}-description`} value={embed.description ?? ''} maxLength={MESSAGE_MODEL_LIMITS.maxEmbedDescription} onChange={(event) => updateEmbed(embedIndex, { description: event.target.value })} /></label>
        <Input labelKey="campaigns.messageModel.embedUrl" id={`${idPrefix}-embed-${embedIndex}-url`} type="url" value={embed.url ?? ''} onChange={(event) => updateEmbed(embedIndex, { url: event.target.value })} />
        <Input labelKey="campaigns.messageModel.embedColor" id={`${idPrefix}-embed-${embedIndex}-color`} type="number" min={0} max={16777215} value={embed.color ?? ''} onChange={(event) => updateEmbed(embedIndex, { color: event.target.value ? Number(event.target.value) : null })} />
        <Input labelKey="campaigns.messageModel.embedFooter" id={`${idPrefix}-embed-${embedIndex}-footer`} value={embed.footer_text ?? ''} maxLength={MESSAGE_MODEL_LIMITS.maxEmbedFooter} onChange={(event) => updateEmbed(embedIndex, { footer_text: event.target.value })} />
        <Input labelKey="campaigns.messageModel.embedAuthor" id={`${idPrefix}-embed-${embedIndex}-author`} value={embed.author_name ?? ''} maxLength={MESSAGE_MODEL_LIMITS.maxEmbedAuthorName} onChange={(event) => updateEmbed(embedIndex, { author_name: event.target.value })} />
        <div className="message-model-fields">
          <h5>{t('campaigns.messageModel.fields')}</h5>
          {embed.fields.map((field, fieldIndex) => <div className="message-model-field" key={fieldIndex}>
            <Input labelKey="campaigns.messageModel.fieldName" id={`${idPrefix}-embed-${embedIndex}-field-${fieldIndex}-name`} value={field.name} maxLength={MESSAGE_MODEL_LIMITS.maxEmbedFieldName} onChange={(event) => updateField(embedIndex, fieldIndex, { name: event.target.value })} />
            <Input labelKey="campaigns.messageModel.fieldValue" id={`${idPrefix}-embed-${embedIndex}-field-${fieldIndex}-value`} value={field.value} maxLength={MESSAGE_MODEL_LIMITS.maxEmbedFieldValue} onChange={(event) => updateField(embedIndex, fieldIndex, { value: event.target.value })} />
            <label><input type="checkbox" checked={field.inline} onChange={(event) => updateField(embedIndex, fieldIndex, { inline: event.target.checked })} /> {t('campaigns.messageModel.fieldInline')}</label>
            <Button type="button" labelKey="campaigns.messageModel.removeField" onClick={() => removeField(embedIndex, fieldIndex)} />
          </div>)}
          <Button type="button" labelKey="campaigns.messageModel.addField" disabled={embed.fields.length >= MESSAGE_MODEL_LIMITS.maxEmbedFields} onClick={() => addField(embedIndex)} />
        </div>
        <Button type="button" labelKey="campaigns.messageModel.removeEmbed" onClick={() => removeEmbed(embedIndex)} />
      </div>)}
      <Button type="button" labelKey="campaigns.messageModel.addEmbed" disabled={embeds.length >= MESSAGE_MODEL_LIMITS.maxEmbeds} onClick={addEmbed} />
    </section>

    <section className="message-model-components">
      <h4>{t('campaigns.messageModel.components')}</h4>
      {actionRows.map((row, rowIndex) => <div className="message-model-row" key={rowIndex}>
        {row.buttons.map((button, buttonIndex) => <div className="message-model-button" key={buttonIndex}>
          <Input labelKey="campaigns.messageModel.buttonLabel" id={`${idPrefix}-row-${rowIndex}-button-${buttonIndex}-label`} value={button.label} maxLength={80} onChange={(event) => updateButton(rowIndex, buttonIndex, { label: event.target.value })} />
          <Select labelKey="campaigns.messageModel.buttonStyle" id={`${idPrefix}-row-${rowIndex}-button-${buttonIndex}-style`} value={button.style} onChange={(event) => setButtonStyle(rowIndex, buttonIndex, event.target.value as ButtonStyle)}>
            {buttonStyles.map((style) => <option key={style} value={style}>{t(buttonStyleKeys[style])}</option>)}
          </Select>
          {button.style === 'LINK'
            ? <Input labelKey="campaigns.messageModel.buttonUrl" id={`${idPrefix}-row-${rowIndex}-button-${buttonIndex}-url`} type="url" value={button.url ?? ''} onChange={(event) => updateButton(rowIndex, buttonIndex, { url: event.target.value })} />
            : <Input labelKey="campaigns.messageModel.buttonCustomId" id={`${idPrefix}-row-${rowIndex}-button-${buttonIndex}-customid`} value={button.custom_id ?? ''} maxLength={100} onChange={(event) => updateButton(rowIndex, buttonIndex, { custom_id: event.target.value })} />}
          <Button type="button" labelKey="campaigns.messageModel.removeButton" onClick={() => removeButton(rowIndex, buttonIndex)} />
        </div>)}
        <Button type="button" labelKey="campaigns.messageModel.addButton" disabled={row.buttons.length >= MESSAGE_MODEL_LIMITS.maxButtonsPerRow} onClick={() => addButton(rowIndex)} />
        <Button type="button" labelKey="campaigns.messageModel.removeRow" onClick={() => removeRow(rowIndex)} />
      </div>)}
      <Button type="button" labelKey="campaigns.messageModel.addRow" disabled={actionRows.length >= MESSAGE_MODEL_LIMITS.maxActionRows} onClick={addRow} />
    </section>
  </div>
}
