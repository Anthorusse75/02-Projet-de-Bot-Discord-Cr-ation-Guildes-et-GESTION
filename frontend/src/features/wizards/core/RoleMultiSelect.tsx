import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { Role } from '../../../api/types'
import { Badge, Dialog } from '../../../shared/components/ui'
import type { MessageKey } from '../../../localization/catalog'
import { validateDiscordResourceName } from '../../structure/naming'

export type ProposedRole = { id: string; name: string }

export interface RoleMultiSelectProps {
  roles: readonly Role[]
  selectedRoleIds: readonly string[]
  proposedRoles: readonly ProposedRole[]
  onToggleRole: (roleId: string) => void
  onAddProposedRole: (role: ProposedRole) => void
  onRemoveProposedRole: (id: string) => void
  disabled?: boolean
  /** Optional suggested role name (REQ-WIZ-006), e.g. when the chosen intent has no audience yet. */
  suggestedName?: string | undefined
}

/**
 * Reusable multi-role picker (REQ-WIZ-005/006/007). Existing roles are always multi-selectable;
 * managed/integration roles stay visible but disabled with an explanation instead of being
 * silently filtered out. "+ Créer un rôle" only ever adds a local proposal — it never calls the
 * DSG/Plan API, so no Discord role is created from this component.
 */
export function RoleMultiSelect({ roles, selectedRoleIds, proposedRoles, onToggleRole, onAddProposedRole, onRemoveProposedRole, disabled, suggestedName }: RoleMultiSelectProps) {
  const { t } = useTranslation()
  const [creating, setCreating] = useState(false)
  const [draftName, setDraftName] = useState('')
  const sortedRoles = [...roles].sort((a, b) => b.position - a.position)
  const validation = validateDiscordResourceName(draftName)

  function openCreate(prefill = '') {
    setDraftName(prefill)
    setCreating(true)
  }

  function confirmCreate() {
    if (!validation.valid) return
    onAddProposedRole({ id: `proposed-${crypto.randomUUID()}`, name: draftName.trim() })
    setCreating(false)
  }

  return (
    <div className="wizard-role-select">
      <div className="wizard-role-list" role="group" aria-label={t('wizard.roles.existing')}>
        {sortedRoles.map((role) => {
          const unusable = role.managed
          return (
            <label key={role.id} className={unusable ? 'wizard-role-row unusable' : 'wizard-role-row'} title={unusable ? t('wizard.roles.managedHelp') : undefined}>
              <input
                type="checkbox"
                checked={selectedRoleIds.includes(role.id)}
                disabled={disabled || unusable}
                onChange={() => onToggleRole(role.id)}
              />
              <span>{role.name}</span>
              {unusable && <Badge tone="warning">{t('wizard.roles.managed')}</Badge>}
            </label>
          )
        })}
        {sortedRoles.length === 0 && <p className="access-help">{t('wizard.roles.empty')}</p>}
      </div>

      {suggestedName && selectedRoleIds.length === 0 && !proposedRoles.some((role) => role.name === suggestedName) && (
        <div className="access-callout warning wizard-role-suggestion">
          <span>{t('wizard.roles.suggested', { name: suggestedName })}</span>
          <button type="button" className="button quiet" disabled={disabled} onClick={() => openCreate(suggestedName)}>{t('wizard.roles.useSuggestion')}</button>
        </div>
      )}

      {proposedRoles.length > 0 && (
        <ul className="wizard-proposed-roles" aria-label={t('wizard.roles.proposed')}>
          {proposedRoles.map((role) => (
            <li key={role.id}>
              <Badge tone="warning">{t('wizard.roles.willBeCreated')}</Badge>
              <span>{role.name}</span>
              <button type="button" className="button quiet" disabled={disabled} onClick={() => onRemoveProposedRole(role.id)}>{t('wizard.roles.removeProposed')}</button>
            </li>
          ))}
        </ul>
      )}

      <button type="button" className="button quiet" disabled={disabled} onClick={() => openCreate()}>{t('wizard.roles.create')}</button>

      <Dialog open={creating} titleKey={'wizard.roles.create' as MessageKey} onClose={() => setCreating(false)}>
        <label className="field">
          <span>{t('wizard.roles.createName')}</span>
          <input
            autoFocus
            value={draftName}
            aria-invalid={!validation.valid}
            onChange={(event) => setDraftName(event.target.value)}
            onKeyDown={(event) => { if (event.key === 'Enter' && validation.valid) { event.preventDefault(); confirmCreate() } }}
          />
        </label>
        {!validation.valid && draftName.length > 0 && <p className="access-callout danger" role="alert">{t(validation.reason === 'empty' ? 'structure.naming.empty' : 'structure.naming.tooLong')}</p>}
        <p className="access-help">{t('wizard.roles.createHelp')}</p>
        <div className="button-row">
          <button type="button" className="button primary" disabled={!validation.valid} onClick={confirmCreate}>{t('wizard.roles.confirmCreate')}</button>
        </div>
      </Dialog>
    </div>
  )
}
