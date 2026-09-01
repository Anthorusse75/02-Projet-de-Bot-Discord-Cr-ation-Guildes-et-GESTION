import type { MessageKey } from './catalog'

const planStatuses: Record<string, MessageKey> = {
  DRAFT: 'plans.status.draft', VALIDATED: 'plans.status.validated', CONFIRMED: 'plans.status.confirmed', APPLYING: 'plans.status.applying',
  CANCEL_REQUESTED: 'plans.status.cancel_requested', CANCELLED: 'plans.status.cancelled', STALE: 'plans.status.stale', SUCCEEDED: 'plans.status.succeeded',
  APPLIED_WITH_PENDING_PROVIDER: 'plans.status.applied_with_pending_provider',
  FAILED: 'plans.status.failed', PARTIALLY_APPLIED: 'plans.status.partially_applied', VERIFICATION_FAILED: 'plans.status.verification_failed', INTERVENTION_REQUIRED: 'plans.status.intervention_required',
}
const risks: Record<string, MessageKey> = { LOW: 'risk.low', MEDIUM: 'risk.medium', HIGH: 'risk.high' }
const progress: Record<string, MessageKey> = {
  'plans.progress.created': 'plans.progress.created', 'plans.progress.validated': 'plans.progress.validated', 'plans.progress.confirmed': 'plans.progress.confirmed',
  'plans.progress.applying': 'plans.progress.applying', 'plans.progress.cancel_requested': 'plans.progress.cancel_requested', 'plans.progress.cancelled': 'plans.progress.cancelled',
  'plans.progress.stale': 'plans.progress.stale', 'plans.progress.succeeded': 'plans.progress.succeeded', 'plans.progress.failed': 'plans.progress.failed',
  'plans.progress.applied_with_pending_provider': 'plans.progress.applied_with_pending_provider',
  'plans.progress.partially_applied': 'plans.progress.partially_applied', 'plans.progress.verification_failed': 'plans.progress.verification_failed',
  'plans.progress.intervention_required': 'plans.progress.intervention_required', 'plans.progress.preconditionRejected': 'plans.progress.preconditionRejected',
  'plans.progress.operationSucceeded': 'plans.progress.operationSucceeded', 'plans.progress.operationUnknown': 'plans.progress.operationUnknown',
  'plans.progress.operationRetryScheduled': 'plans.progress.operationRetryScheduled', 'plans.progress.operationFailed': 'plans.progress.operationFailed',
}

const artifacts: Record<string, MessageKey> = {
  CHANNEL: 'artifact.channel', CATEGORY: 'artifact.category', LOGICAL_GROUP: 'artifact.logicalGroup',
  GUILD_CONFIG: 'artifact.guildConfig', CUSTOM_BUNDLE: 'artifact.customBundle',
}
const permissionReasons: Record<string, MessageKey> = {
  'permissions.trace.baseEveryone': 'permissions.trace.baseEveryone',
  'permissions.trace.baseRole': 'permissions.trace.baseRole',
  'permissions.trace.baseRolesOr': 'permissions.trace.baseRolesOr',
  'permissions.trace.ownerBypass': 'permissions.trace.ownerBypass',
  'permissions.trace.administratorBypass': 'permissions.trace.administratorBypass',
  'permissions.trace.everyoneDeny': 'permissions.trace.everyoneDeny',
  'permissions.trace.roleDeniesAggregate': 'permissions.trace.roleDeniesAggregate',
  'permissions.trace.memberDeny': 'permissions.trace.memberDeny',
  'permissions.trace.everyoneAllow': 'permissions.trace.everyoneAllow',
  'permissions.trace.roleAllowsAggregate': 'permissions.trace.roleAllowsAggregate',
  'permissions.trace.memberAllow': 'permissions.trace.memberAllow',
  'permissions.trace.threadInheritance': 'permissions.trace.threadInheritance',
  'permissions.trace.implicitDenial': 'permissions.trace.implicitDenial',
  'permissions.trace.coverageIncomplete': 'permissions.trace.coverageIncomplete',
}
const coverageStates: Record<string, MessageKey> = {
  FULL: 'diagnostics.state.full', PARTIAL: 'diagnostics.state.partial', UNKNOWN: 'diagnostics.state.unknown',
  FRESH: 'diagnostics.state.fresh', STALE: 'diagnostics.state.stale',
}
const auditResults: Record<string, MessageKey> = {
  SUCCEEDED: 'audit.result.succeeded', SUCCESS: 'audit.result.succeeded', APPLIED: 'audit.result.succeeded',
  VERIFIED: 'audit.result.succeeded', OBSERVED: 'audit.result.observed', VISIBLE: 'audit.result.observed',
  FAILED: 'audit.result.failed', REJECTED: 'audit.result.failed', STALE: 'audit.result.stale',
  INTERVENTION_REQUIRED: 'audit.result.intervention', UNKNOWN: 'common.unknown',
}

export const planStatusKey = (value: string): MessageKey => planStatuses[value] ?? 'common.unknown'
export const riskKey = (value: string): MessageKey => risks[value] ?? 'common.unknown'
export const progressMessageKey = (value: string): MessageKey => progress[value] ?? 'common.unknown'
export const artifactTypeKey = (value: string): MessageKey => artifacts[value] ?? 'artifact.unknown'
export const permissionReasonKey = (value: string): MessageKey => permissionReasons[value] ?? 'permissions.trace.generic'
export const coverageStateKey = (value: unknown): MessageKey => coverageStates[String(value)] ?? 'common.unknown'
export const auditResultKey = (value: string): MessageKey => auditResults[value] ?? 'common.unknown'
export function auditEventKey(value: string): MessageKey {
  if (value.includes('INSTALLATION')) return 'audit.event.installation'
  if (value.includes('PLAN')) return 'audit.event.plan'
  if (value.includes('PORTABLE') || value.includes('ARTIFACT') || value.includes('TEMPLATE') || value.includes('CROSS_GUILD')) return 'audit.event.portability'
  if (value.includes('ROLE')) return 'audit.event.role'
  if (value.includes('CHANNEL') || value.includes('THREAD') || value.includes('GUILD')) return 'audit.event.structure'
  return 'audit.event.generic'
}
// STAGE 09 -- campaigns
const campaignStatuses: Record<string, MessageKey> = {
  DRAFT: 'campaigns.status.draft', SCHEDULED_ARMED: 'campaigns.status.scheduledArmed', ACTIVE_RUNNING: 'campaigns.status.activeRunning',
  PAUSED: 'campaigns.status.paused', CANCELLED: 'campaigns.status.cancelled', COMPLETED: 'campaigns.status.completed',
  FAILED_INTERVENTION: 'campaigns.status.failedIntervention',
}
const publicationModes: Record<string, MessageKey> = {
  IMMEDIATE: 'campaigns.publicationMode.immediate', ONE_SHOT_DEFERRED: 'campaigns.publicationMode.oneShotDeferred',
  RECURRING: 'campaigns.publicationMode.recurring', EVENT_TRIGGERED: 'campaigns.publicationMode.eventTriggered',
}
const attachmentPolicies: Record<string, MessageKey> = {
  PRESERVE_EXISTING: 'campaigns.attachmentPolicy.preserveExisting', REPLACE_ALL: 'campaigns.attachmentPolicy.replaceAll', REMOVE_ALL: 'campaigns.attachmentPolicy.removeAll',
}
const targetKinds: Record<string, MessageKey> = {
  CHANNEL: 'campaigns.targets.kind.channel', TRANSLATION_GROUP: 'campaigns.targets.kind.translationGroup', LOGICAL_GROUP: 'campaigns.targets.kind.logicalGroup',
}
const deliveryStatuses: Record<string, MessageKey> = {
  PENDING: 'campaigns.delivery.status.pending', CLAIMED: 'campaigns.delivery.status.claimed', SENDING: 'campaigns.delivery.status.sending',
  SENT: 'campaigns.delivery.status.sent', FAILED: 'campaigns.delivery.status.failed', UNKNOWN: 'campaigns.delivery.status.unknown',
  INTERVENTION_REQUIRED: 'campaigns.delivery.status.interventionRequired',
}
const blockedReasons: Record<string, MessageKey> = {
  GUILD_NOT_AUTHORIZED: 'campaigns.blocked.guildNotAuthorized', BOT_CANNOT_SEND: 'campaigns.blocked.botCannotSend',
  TRANSLATION_GROUP_NOT_FOUND: 'campaigns.blocked.translationGroupNotFound', NO_MATCHING_LANGUAGE_VARIANTS: 'campaigns.blocked.noMatchingLanguageVariants',
  LOGICAL_GROUP_NOT_FOUND: 'campaigns.blocked.logicalGroupNotFound', LOGICAL_GROUP_EMPTY: 'campaigns.blocked.logicalGroupEmpty',
  PROVIDER_SAFETY_MANUAL_CONFIGURATION_REQUIRED: 'campaigns.blocked.providerSafetyManualConfigurationRequired',
}
const translationStates: Record<string, MessageKey> = {
  SOURCE: 'campaigns.translationState.source', REUSABLE_APPROVED: 'campaigns.translationState.reusableApproved',
  STALE_APPROVED_WOULD_RETRANSLATE: 'campaigns.translationState.staleApprovedWouldRetranslate', MISSING_WOULD_TRANSLATE: 'campaigns.translationState.missingWouldTranslate',
  MISSING_NO_PROVIDER_CONFIGURED: 'campaigns.translationState.missingNoProviderConfigured',
}
const variantOutcomes: Record<string, MessageKey> = {
  REUSABLE: 'campaigns.variants.outcome.reusable', STALE: 'campaigns.variants.outcome.stale', MISSING: 'campaigns.variants.outcome.missing',
}
// Every code did.api.main / did.api.stage09 raise for a campaign-scoped
// request -- an unrecognized code (a future backend addition this UI has
// not been updated for yet) always falls back to errors.generic rather
// than ever rendering a raw ApiProblem.code to the user.
const campaignErrorCodes: Record<string, MessageKey> = {
  CAMPAIGNS_NOT_CONFIGURED: 'errors.campaigns.notConfigured', CAMPAIGN_INPUT_INVALID: 'errors.campaigns.inputInvalid',
  CAMPAIGN_UPDATE_CONFLICT: 'errors.campaigns.updateConflict', CAMPAIGN_TARGET_INPUT_INVALID: 'errors.campaigns.targetInputInvalid',
  CAMPAIGN_SCHEDULE_INPUT_INVALID: 'errors.campaigns.scheduleInputInvalid', CAMPAIGN_LIFECYCLE_CONFLICT: 'errors.campaigns.lifecycleConflict',
  CAMPAIGN_ACTIVATION_CONFLICT: 'errors.campaigns.activationConflict', CAMPAIGN_VARIANT_INPUT_INVALID: 'errors.campaigns.variantInputInvalid',
  CAMPAIGN_RESOURCE_NOT_FOUND: 'errors.campaigns.notFound', CAMPAIGN_GUILD_NOT_AUTHORIZED: 'errors.campaigns.guildNotAuthorized',
  CAMPAIGN_RESOURCE_TYPE_MISMATCH: 'errors.campaigns.resourceTypeMismatch',
}
export const campaignStatusKey = (value: string): MessageKey => campaignStatuses[value] ?? 'common.unknown'
export const publicationModeKey = (value: string): MessageKey => publicationModes[value] ?? 'common.unknown'
export const attachmentPolicyKey = (value: string): MessageKey => attachmentPolicies[value] ?? 'common.unknown'
export const targetKindKey = (value: string): MessageKey => targetKinds[value] ?? 'common.unknown'
export const deliveryStatusKey = (value: string): MessageKey => deliveryStatuses[value] ?? 'common.unknown'
export const blockedReasonKey = (value: string | null): MessageKey => (value ? blockedReasons[value] ?? 'common.unknown' : 'common.unknown')
export const translationStateKey = (value: string): MessageKey => translationStates[value] ?? 'common.unknown'
export const variantOutcomeKey = (value: string): MessageKey => variantOutcomes[value] ?? 'common.unknown'
export const campaignErrorKey = (code: string): MessageKey => campaignErrorCodes[code] ?? 'errors.generic'

export function auditTargetKey(value: string): MessageKey {
  if (value === 'ROLE') return 'resource.role'
  if (value === 'CHANNEL') return 'resource.channel'
  if (value === 'THREAD') return 'resource.thread'
  if (value === 'GUILD') return 'resource.guild'
  if (value === 'TEMPLATE') return 'resource.template'
  if (value.includes('ARTIFACT') || value === 'TRANSFER') return 'resource.artifact'
  return 'common.unknown'
}
