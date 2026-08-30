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
export function auditTargetKey(value: string): MessageKey {
  if (value === 'ROLE') return 'resource.role'
  if (value === 'CHANNEL') return 'resource.channel'
  if (value === 'THREAD') return 'resource.thread'
  if (value === 'GUILD') return 'resource.guild'
  if (value === 'TEMPLATE') return 'resource.template'
  if (value.includes('ARTIFACT') || value === 'TRANSFER') return 'resource.artifact'
  return 'common.unknown'
}
