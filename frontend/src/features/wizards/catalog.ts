export type WizardAvailability = 'available' | 'unavailable'

export interface WizardCatalogEntry {
  id: string
  titleKey: string
  goalKey: string
  scopeKey: string
  producesKey: string
  prerequisitesKey: string
  complexityKey: string
  availability: WizardAvailability
  unavailableReasonKey?: string
  route?: string
}

/**
 * Deliberately small (REQ-WIZ-002): one real, fully working assistant plus one entry marked
 * unavailable to show the catalog shape future phases (Templates, Campaigns) will extend — never
 * a placeholder pretending to be usable.
 */
export const wizardCatalog: readonly WizardCatalogEntry[] = [
  {
    id: 'access-space',
    titleKey: 'wizards.catalog.accessSpace.title',
    goalKey: 'wizards.catalog.accessSpace.goal',
    scopeKey: 'wizards.catalog.accessSpace.scope',
    producesKey: 'wizards.catalog.accessSpace.produces',
    prerequisitesKey: 'wizards.catalog.accessSpace.prerequisites',
    complexityKey: 'wizards.catalog.accessSpace.complexity',
    availability: 'available',
    route: 'access-space',
  },
  {
    id: 'templates',
    titleKey: 'wizards.catalog.templates.title',
    goalKey: 'wizards.catalog.templates.goal',
    scopeKey: 'wizards.catalog.templates.scope',
    producesKey: 'wizards.catalog.templates.produces',
    prerequisitesKey: 'wizards.catalog.templates.prerequisites',
    complexityKey: 'wizards.catalog.templates.complexity',
    availability: 'unavailable',
    unavailableReasonKey: 'wizards.catalog.templates.unavailable',
  },
]
