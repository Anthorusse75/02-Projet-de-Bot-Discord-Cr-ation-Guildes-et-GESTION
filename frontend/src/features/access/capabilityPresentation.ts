import type { CapabilityDecision, CapabilityOutcome } from '../../api/types'

export type CapabilityRequestState = CapabilityOutcome | 'LOADING' | 'ERROR'

export type CapabilityPresentation = {
  state: CapabilityRequestState
  reasonKey: string | undefined
  remediationKeys: string[]
}

const causeMessages: Record<string, string> = {
  'capability.permission_missing.manage_roles': 'capability.cause.missingManageRoles',
  'capability.hierarchy.bot_role_not_above_target': 'capability.cause.botRoleNotAboveTarget',
  'capability.hierarchy.target_managed': 'capability.cause.targetManaged',
  'capability.hierarchy.default_role_reorder_forbidden': 'capability.cause.defaultRole',
  'capability.hierarchy.default_role_mutation_forbidden': 'capability.cause.defaultRole',
  'capability.hierarchy.bot_roles_incomplete': 'capability.cause.botRolesIncomplete',
  'capability.hierarchy.target_or_bot_role_missing': 'capability.cause.roleSnapshotMissing',
  'capability.bot_identity_unknown': 'capability.cause.botIdentityUnknown',
  'capability.installation_not_active': 'capability.cause.installationNotActive',
  'capability.required_intent_missing': 'capability.cause.requiredIntentMissing',
  'coverage.guild_not_full': 'capability.cause.discordDataIncomplete',
  'coverage.guild_not_current': 'capability.cause.discordDataIncomplete',
  'coverage.member_roles_incomplete': 'capability.cause.botRolesIncomplete',
  'coverage.member_roles_not_current': 'capability.cause.botRolesIncomplete',
}

const remediationMessages: Record<string, string> = {
  'capability.remediation.grant.manage_roles': 'capability.remediation.grantManageRoles',
  'capability.remediation.move_bot_role_above_target': 'capability.remediation.moveBotRoleAboveTarget',
  'capability.remediation.refresh_discord_data': 'capability.remediation.refreshDiscordData',
  'capability.remediation.restore_installation': 'capability.remediation.restoreInstallation',
  'capability.remediation.restore_required_intent': 'capability.remediation.restoreRequiredIntent',
}

export function capabilityPresentation({
  isLoading,
  isError,
  decision,
}: {
  isLoading: boolean
  isError: boolean
  decision: CapabilityDecision | undefined
}): CapabilityPresentation {
  if (isLoading) return { state: 'LOADING', reasonKey: undefined, remediationKeys: [] }
  if (isError) return { state: 'ERROR', reasonKey: 'capability.queryError', remediationKeys: [] }
  if (!decision) {
    return {
      state: 'UNKNOWN',
      reasonKey: 'capability.cause.responseIncomplete',
      remediationKeys: ['capability.remediation.refreshDiscordData'],
    }
  }

  const cause = decision.causes.find((item) => causeMessages[item])
  const remediationKeys = [...new Set(decision.remediations.map((item) => remediationMessages[item]).filter((item): item is string => Boolean(item)))]
  if (decision.outcome === 'UNKNOWN' && remediationKeys.length === 0) {
    remediationKeys.push('capability.remediation.refreshDiscordData')
  }
  return {
    state: decision.outcome,
    reasonKey: cause ? causeMessages[cause] : decision.outcome === 'CAN' ? undefined : 'capability.cause.unclassified',
    remediationKeys,
  }
}
