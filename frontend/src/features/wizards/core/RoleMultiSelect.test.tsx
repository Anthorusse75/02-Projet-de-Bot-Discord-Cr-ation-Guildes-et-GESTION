import { useState } from 'react'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { discordSnowflake } from '../../../shared/discord-id'
import { RoleMultiSelect, type ProposedRole } from './RoleMultiSelect'

const apiRequestMock = vi.hoisted(() => vi.fn())
vi.mock('../../../api/client', () => ({ apiRequest: (...args: unknown[]) => apiRequestMock(...args) }))
vi.mock('react-i18next', async () => {
  const { phase4WizardPacks } = await import('../../../localization/phase4WizardCatalog')
  const { phase4Packs } = await import('../../../localization/phase4Catalog')
  return {
    useTranslation: () => ({
      t: (key: string, params: Record<string, string | number> = {}) => {
        const template = (phase4WizardPacks.en as Record<string, string>)[key] ?? (phase4Packs.en as Record<string, string>)[key] ?? key
        return template.replace(/{{\s*([\w.-]+)\s*}}/g, (_, name: string) => String(params[name] ?? ''))
      },
    }),
  }
})

const roles = [
  { id: discordSnowflake('700000000000000011'), name: 'Managers', position: 5, permissions: '0', known_flags: [], unknown_bits: '0', managed: false, freshness: 'FRESH' },
  { id: discordSnowflake('700000000000000012'), name: 'DID Bot', position: 9, permissions: '0', known_flags: [], unknown_bits: '0', managed: true, freshness: 'FRESH' },
]

function Harness({ suggestedName }: { suggestedName?: string | undefined }) {
  const [selected, setSelected] = useState<string[]>([])
  const [proposed, setProposed] = useState<ProposedRole[]>([])
  return (
    <RoleMultiSelect
      roles={roles}
      selectedRoleIds={selected}
      proposedRoles={proposed}
      onToggleRole={(id) => setSelected((prev) => (prev.includes(id) ? prev.filter((v) => v !== id) : [...prev, id]))}
      onAddProposedRole={(role) => setProposed((prev) => [...prev, role])}
      onRemoveProposedRole={(id) => setProposed((prev) => prev.filter((role) => role.id !== id))}
      suggestedName={suggestedName}
    />
  )
}

describe('RoleMultiSelect', () => {
  beforeEach(() => apiRequestMock.mockReset())

  it('shows managed roles but flags them as unusable instead of hiding them', () => {
    render(<Harness />)
    const managedCheckbox = screen.getByRole('checkbox', { name: /DID Bot/ })
    expect(managedCheckbox).toBeDisabled()
    expect(screen.getByRole('checkbox', { name: /Managers/ })).toBeEnabled()
  })

  it('a suggested or manually created role becomes a local proposal and never calls the backend (REQ-WIZ-006)', async () => {
    const user = userEvent.setup()
    render(<Harness suggestedName="Confirmed members" />)

    await user.click(screen.getByRole('button', { name: 'Use this suggestion' }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByRole('textbox')).toHaveValue('Confirmed members')
    await user.click(within(dialog).getByRole('button', { name: 'Add this proposal' }))

    expect(screen.getByText('Will be created')).toBeVisible()
    expect(screen.getByText('Confirmed members')).toBeVisible()
    // The role is only ever a client-side proposal until a Plan is prepared elsewhere.
    expect(apiRequestMock).not.toHaveBeenCalled()
  })
})
