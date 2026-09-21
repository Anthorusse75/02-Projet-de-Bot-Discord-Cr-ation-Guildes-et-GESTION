import type { DiscordSnowflake } from '../shared/discord-id'

export type ApiErrorEnvelope = { error: { code: string; message_key: string; params: Record<string, string | number>; request_id: string } }
export type Me = { authenticated: true; user: { discord_user_id: DiscordSnowflake; username: string; global_name: string | null }; active_guild_id: DiscordSnowflake | null; csrf_token: string; policy_version: number }
export type Guild = { guild_id: DiscordSnowflake; name: string; owner: boolean; permissions: string; installation_status: string | null }
export type Channel = { guild_id: DiscordSnowflake; id: DiscordSnowflake; type: number; name: string; position: number; parent_id: DiscordSnowflake | null; resource_kind: string; observability: string; freshness: string; data_assertion: string; threads?: Channel[] }
export type Structure = { guild_id: DiscordSnowflake; source: 'LOCAL_CACHE'; discord_rest_calls: 0; categories: Array<Channel & { channels: Channel[] }>; root_channels: Channel[] }
export type Role = { id: DiscordSnowflake; name: string; position: number; permissions: string; known_flags: string[]; unknown_bits: string; managed: boolean; freshness: string }
export type Roles = { guild_id: DiscordSnowflake; source: 'LOCAL_CACHE'; roles: Role[] }
export type PolicyLifecycle = 'DRAFT'|'ACTIVE'|'DISABLED'|'RETIRED'
export type PolicyScopeType = 'GUILD'|'LOGICAL_GROUP'|'CATEGORY'|'CHANNEL'|'ROLE'|'MEMBER'|'BOT'
export type PolicyAccess = 'VIEW'|'WRITE'|'MANAGE'|'CONNECT'|'SPEAK'|'MANAGE_VOICE'|'CREATE_THREAD'|'PARTICIPATE_THREAD'|'REACT'|'MENTION_EVERYONE_HERE'|'READ_HISTORY'|'SEND'|'MANAGE_CHANNEL'
export type PolicyCondition = { kind: 'ALWAYS' } | { kind: 'ROLE_MATCH'; match: 'ANY'|'ALL'; role_ids: string[] } | { kind: 'ROLE_EXCLUDE'; match: 'ANY'|'ALL'; role_ids: string[] } | { kind: 'SUBJECT_KIND'; subject_kind: 'MEMBER'|'BOT' } | { kind: 'BOT_MATCH'; bot_user_ids: string[] }
export type PolicyEffect = { kind: 'SET_ACCESS'; access: PolicyAccess; decision: 'ALLOW'|'DENY'; audience?: { mode:'INCLUDE'|'EXCLUDE'; match:'ANY'|'ALL'; role_ids:string[] } }
export type PolicyMetadata = { summary: string; tags: string[]; reason: string | null }
export type Policy = { policy_id: string; guild_id: DiscordSnowflake; policy_type: 'ACCESS_CONTROL'; contract_version: number; name: string; description: string; lifecycle_state: PolicyLifecycle; revision: number; priority: number; locked: boolean; scope_type: PolicyScopeType; scope_id: string | null; conditions: PolicyCondition[]; effects: PolicyEffect[]; metadata: PolicyMetadata; created_by_user_id: DiscordSnowflake; modified_by_user_id: DiscordSnowflake; created_at: string | null; updated_at: string | null; activated_at: string | null; disabled_at: string | null; retired_at: string | null }
export type PolicyFavorites = { guild_id: DiscordSnowflake; favorite_keys: string[] }
export type PolicyTemporaryAccess = { guild_id:DiscordSnowflake; policy_id:string; expires_at:string; status:'SCHEDULED'|'PROCESSING'|'REMOVAL_SCHEDULED'|'REMOVED'|'INTERVENTION_REQUIRED'|'CANCELLED'; removal_plan_id:string|null; attempt_count:number; last_error:string|null; created_at:string|null; updated_at:string|null; removal_started_at:string|null; completed_at:string|null }
export type PolicyVersion = { version_id: string; guild_id: DiscordSnowflake; policy_id: string; revision: number; change_kind: string; snapshot: Policy; author_user_id: DiscordSnowflake; correlation_id: string; idempotency_key: string | null; created_at: string }
export type PolicyConflict = { policy_ids: string[]; revisions: number[]; source_scopes: string[]; effects: string[]; resolution_rule: string | null; outcome: 'RESOLVED'|'BLOCKED'; winning_policy_ids: string[] }
export type PolicyContribution = { policy_id: string; revision: number; effect_index: number; priority: number; scope_type: PolicyScopeType; scope_id: string | null; family: string; specificity: number; inherited: boolean; access: PolicyAccess; decision: 'ALLOW'|'DENY'; condition_outcome: 'TRUE'|'FALSE'|'UNKNOWN'; selected: boolean; disposition: string }
export type PolicyConditionEvaluation = { policy_id: string; revision: number; condition_index: number; kind: string; outcome: 'TRUE'|'FALSE'|'UNKNOWN'; reason: string }
export type ConflictCauseRole = { role_id: DiscordSnowflake; source_policy_id: string; source: 'CONDITION'|'AUDIENCE_INCLUDE' }
export type ConflictExplanation = { conflict: PolicyConflict; accepted: boolean; causing_roles: ConflictCauseRole[]; reason_key: string; remediations?:ConflictRemediation[] }
export type BlacklistRegrant = { excluding_policy_id: string; excluding_role_ids: DiscordSnowflake[]; regranting_policy_id: string; regranting_role_ids: ConflictCauseRole[]; accepted: boolean; reason_key: string }
export type ObservableConflictCause = { kind:'OWNER'|'ADMINISTRATOR'|'BASE_ROLE'|'MEMBER_OVERWRITE'|'ROLE_OVERWRITE'|'EVERYONE_OVERWRITE'|'IMPLICIT_DENIAL'; source_id:string|null; source_name:string|null; decision:'ALLOW'|'DENY'; permission_names:string[]; inherited_from_category_id:string|null; reason_key:string }
export type ConflictRemediation = { kind:'REMOVE_MEMBER_ROLE'|'EDIT_ROLE_OVERWRITE'|'EDIT_MEMBER_OVERWRITE'|'EDIT_EVERYONE_OVERWRITE'|'EDIT_POLICY_DRAFT'; target_id:string; route:'roles'|'matrix'|'policies'; requires_separate_plan:true; collateral_losses:string[]; collateral_scope:string[]; reason_key:string }
export type ObservableAccessConflict = { member_id:DiscordSnowflake; resource_id:DiscordSnowflake; policy_ids:string[]; expected_outcome:'CAN'|'CANNOT'; actual_outcome:'ALLOWED'|'DENIED'; granting_causes:ObservableConflictCause[]; denying_causes:ObservableConflictCause[]; remediations:ConflictRemediation[] }
export type PolicyResolution = { guild_id: DiscordSnowflake; subject_id: DiscordSnowflake; decision: string; outcome: CapabilityOutcome|'BLOCKED'; target_scope_type: 'GUILD'|'LOGICAL_GROUP'|'CATEGORY'|'CHANNEL'; target_scope_id: string | null; target_state: string; target_freshness: string; coverage: string; applicable_policies: Array<{ policy_id:string; revision:number; priority:number; scope_type:PolicyScopeType; scope_id:string|null; inherited:boolean; specificity:number }>; contributions: PolicyContribution[]; conflicts: PolicyConflict[]; source_scopes: Array<{policy_id:string;revision:number;scope_type:PolicyScopeType;scope_id:string|null;family:string;specificity:number;inherited:boolean}>; priority_trace: Array<{policy_id:string;revision:number;effect_index:number;priority:number;family:string;specificity:number;canonical_position:number;disposition:string;resolution_rule:string|null}>; conditions: PolicyConditionEvaluation[]; incomplete_reasons: string[]; warnings: string[]; source_versions: string[]; discord_permissions: string[]; discord_allow_bits: string; discord_deny_bits: string; discord_translation_diagnostics: string[]; conflict_explanations?: ConflictExplanation[]; blacklist_regrants?: BlacklistRegrant[]; observable_access_conflict?:ObservableAccessConflict|null }
export type ScopeType = 'GLOBAL'|'LOGICAL_GROUP'|'STAFF'|'PROJECT'|'CUSTOM'
export type MembershipRuleType = 'DISCORD_ROLE'|'ANY_DISCORD_ROLE'|'ALL_DISCORD_ROLES'|'EXPLICIT_DID_MEMBERSHIP'|'CUSTOM'
export type ScopeMembershipRule = { rule_type: MembershipRuleType; config: { role_ids?: DiscordSnowflake[] }; priority: number; status?: string }
export type VisibilityScope = { id: string; guild_id: DiscordSnowflake; scope_type: ScopeType; scope_key: string; name: string; logical_group_id: string | null; config: Record<string, unknown>; version: number; rules: ScopeMembershipRule[]; explicit_member_ids: DiscordSnowflake[] }
export type PolicyPreviewEntry = { target: { subject_id: DiscordSnowflake; scope_type: PolicyScopeType; scope_id: string | null; requested_access: PolicyAccess }; current: PolicyResolution; proposed: PolicyResolution; access_change: 'UNCHANGED'|'GAINED'|'LOST'|'BLOCKED'|'UNKNOWN'|'RESOLUTION_CHANGED'; gained_contributions: string[]; lost_contributions: string[]; conflicts_created: string[]; conflicts_resolved: string[]; diagnostics: string[]; warnings: string[]; remediations: string[] }
export type PolicyPreview = { policy_id:string; policy_revision:number; lifecycle_state:PolicyLifecycle; scope_type:PolicyScopeType; scope_id:string|null; entries:PolicyPreviewEntry[]; impact:{accuracy:'EXACT'|'BOUNDED'|'INCOMPLETE';candidate_contexts:number;evaluated_contexts:number;affected_resources:number;affected_roles:number;affected_members:number;access_gains:number;access_losses:number;conflicts:number;impossible_or_incomplete_targets:number;lower_bound_only:boolean;diagnostics:string[]}; freshness:string; coverage:string; source_versions:string[]; warnings:string[]; persisted:false; discord_mutations:0 }
export type PolicyDeletionStrategy = 'DETACH'|'REPLACE'|'DELETE_BINDINGS'
export type PolicyDeletionPreview = { policy:Policy; plans:Array<{id:string;source_policy_revision:number;status:string;created_at:string}>; referencing_policies:Array<{policy_id:string;name:string;lifecycle_state:PolicyLifecycle;reference_kinds:Array<'SOURCE'|'EXCEPTION'>}>; bulk_operation_ids:string[]; scope_binding_count:number; available_replacements:Array<{policy_id:string;name:string}>; access_impact:PolicyPreview|null; discord_mutations:0; selected_replacement_valid:boolean; strategies:Array<{strategy:PolicyDeletionStrategy;available:boolean;requires_plan:boolean}> }
export type Plan = { id: string; guild_id: DiscordSnowflake; status: string; state_version: number; plan_hash: string; risk_level: string; impact: Record<string, number>; reinforced_confirmation_required: boolean; created_at: string; updated_at: string; error_code: string | null }
export type AccessSynthesis = 'UNKNOWN'|'NONE'|'VIEW'|'WRITE'|'MANAGE'|'CONNECT'|'SPEAK'
export type AccessMatrixCell = { role_id: DiscordSnowflake; resource_id: DiscordSnowflake; synthesis: AccessSynthesis; permission_status: 'COMPLETE'|'INCOMPLETE'|'UNKNOWN'; policy_outcome: CapabilityOutcome|'BLOCKED'; conflict: boolean; exception: boolean; inherited: boolean; contributing_policy_ids: string[]; conflict_policy_ids: string[]; incomplete_reasons: string[]; role_known: boolean; resource_known: boolean }
export type AccessMatrixResult = { guild_id: DiscordSnowflake; coverage: string; freshness: string; source_versions: string[]; cells: AccessMatrixCell[] }
export type BulkPolicyPreview = { operation_id:string; draft_count:number; discord_mutations:0; items:Array<{policy:Policy;preview:PolicyPreview}> }
export type BulkPolicyPlan = { prepared_count:number; discord_mutations:0; items:Array<{policy_id:string;created:boolean;plan:Plan;preflight:{allowed:boolean;errors:string[];warnings:string[]}}> }
export type AuditEvent = { id: string; event_type: string; target_type: string; target_id: string | null; result_state: string; occurred_at: string; plan_id: string | null; correlation_id: string }
export type PortableArtifact = { id: string; artifact_type: string; kind: string; name: string | null; content_hash: string; created_at: string; expires_at: string | null }
export type Template = { id: string; name: string; artifact_type: string; created_at: string; updated_at: string }
export type CapabilityOutcome = 'CAN' | 'CANNOT' | 'UNKNOWN'
export type CapabilityHierarchy = { outcome: CapabilityOutcome; bot_highest_role_id: DiscordSnowflake | null; bot_highest_position: number | null; target_role_id: DiscordSnowflake | null; target_position: number | null; reasons: string[] }
export type CapabilityDecision = { outcome: CapabilityOutcome; causes: string[]; remediations: string[]; hierarchy?: CapabilityHierarchy | null; warnings?: string[]; scope_kind?: string; scope_id?: string }
export type DashboardCapabilities = {
  guild_id: DiscordSnowflake
  source: 'AUTHORIZATION_AND_LOCAL_CACHE'
  discord_rest_calls: 0
  user_capabilities: Record<string, CapabilityDecision>
  scoped_capabilities: { scope_kind: string; scope_id: string; capabilities: Record<string, CapabilityDecision> }
  bot_operations: Record<string, CapabilityDecision & { operation: string; required_permissions: string[] }>
  coverage: string
  completeness: string
  freshness: string
}
export type PlanProgressEvent = { sequence: number; plan_status: string; message_key: string; completed_operations?: number; total_operations?: number; params?: Record<string, string | number> }
export type LanguageProfile = { id: string; guild_id: DiscordSnowflake; code: string; display_name: string; emoji: string | null; enabled: boolean }
export type DiscordChannelCacheFact = { present: boolean; name: string | null; type: number | null; observability: string; freshness: string }
export type DiscordRoleCacheFact = { present: boolean; name: string | null; managed: boolean | null; permissions: string | null; freshness: string }
export type TranslationVariant = { id: string; language_profile_id: string; discord_category_id?: DiscordSnowflake; discord_channel_id?: DiscordSnowflake; state: string; translation_channel_group_id?: string; translation_category_variant_id?: string | null; discord_cache?: DiscordChannelCacheFact }
export type TranslationChannelGroup = { id: string; logical_key: string; display_name: string; source_language_profile_id: string | null }
export type TranslationRoute = { id: string; source_language_profile_id: string; destination_language_profile_id: string; state: string }
export type TranslationGroup = { id: string; guild_id: DiscordSnowflake; name: string; root_kind: string; routing_mode: string; visibility_scope_id: string | null; source_language_profile_id: string | null; provider_binding_id: string | null; status: string; version: number; languages: LanguageProfile[]; category_variants: TranslationVariant[]; channel_groups: TranslationChannelGroup[]; channel_variants: TranslationVariant[]; routes: TranslationRoute[] }
export type TranslationProviderBinding = { id: string; provider_type: string; status: string; capabilities_json: Record<string, unknown>; last_validated_at: string | null }
export type VisibilityBinding = { id: string; visibility_scope_id: string; language_profile_id: string; discord_role_id: DiscordSnowflake; state: string; discord_cache?: DiscordRoleCacheFact }
export type ResourceLanguagePolicy = { id: string; resource_type: 'CATEGORY'|'CHANNEL'; discord_resource_id: DiscordSnowflake; explicit_language_profile_id: string | null; inherit_language: boolean; visibility_policy: 'OPEN_ALL'|'LANGUAGE_FILTERED'|'SCOPE_AND_LANGUAGE'|'CUSTOM'; visibility_scope_id: string | null }
export type TranslationWorkspace = { guild_id: DiscordSnowflake; source: 'DURABLE_TOPOLOGY_AND_LOCAL_DISCORD_CACHE'; discord_rest_calls: 0; cache_coverage: { mode: string; freshness: string; roles_complete: boolean; channels_complete: boolean; members_complete: boolean; state_version: number }; groups: TranslationGroup[]; providers: TranslationProviderBinding[]; visibility_bindings: VisibilityBinding[]; languages: LanguageProfile[]; resource_language_policies: ResourceLanguagePolicy[] }

// STAGE 09 -- Message & Campaign Engine (see did.api.stage09 for the authoritative response shapes).
export type CampaignLifecycleStatus = 'DRAFT'|'SCHEDULED_ARMED'|'ACTIVE_RUNNING'|'PAUSED'|'CANCELLED'|'COMPLETED'|'FAILED_INTERVENTION'
export type PublicationMode = 'IMMEDIATE'|'ONE_SHOT_DEFERRED'|'RECURRING'|'EVENT_TRIGGERED'
export type CampaignAttachmentPolicy = 'PRESERVE_EXISTING'|'REPLACE_ALL'|'REMOVE_ALL'
export type CampaignTargetKind = 'CHANNEL'|'TRANSLATION_GROUP'|'LOGICAL_GROUP'
export type TranslationPublicationMode = 'SOURCE_ONLY'|'EXISTING_PROVIDER'|'DID_TRANSLATED_FANOUT'|'SELECTED_LANGUAGES'
export type LogicalGroupResource = { resource_type: 'CATEGORY' | 'CHANNEL' | 'ROLE'; discord_channel_id?: DiscordSnowflake | null; discord_role_id?: DiscordSnowflake | null; semantic_role?: string | null }
export type LogicalGroup = { id: string; guild_id: DiscordSnowflake; name: string; slug: string; description: string | null; resources?: LogicalGroupResource[] }
export type ScheduleKind = 'IMMEDIATE'|'ONE_SHOT'|'RECURRING'
export type DeliveryStatus = 'PENDING'|'CLAIMED'|'SENDING'|'SENT'|'FAILED'|'UNKNOWN'|'INTERVENTION_REQUIRED'|'DELETED'
export type VariantOutcome = 'REUSABLE'|'STALE'|'MISSING'
export type ButtonStyle = 'PRIMARY'|'SECONDARY'|'SUCCESS'|'DANGER'|'LINK'
export type EmbedField = { name: string; value: string; inline: boolean }
export type Embed = { title: string | null; description: string | null; url: string | null; color: number | null; footer_text: string | null; author_name: string | null; fields: EmbedField[] }
export type ComponentButton = { label: string; style: ButtonStyle; custom_id: string | null; url: string | null }
export type ComponentActionRow = { buttons: ComponentButton[] }
export type MessageModel = { content: string; embeds: Embed[]; action_rows: ComponentActionRow[] }
export type AllowedMentionsPolicy = { allow_everyone?: boolean; allowed_user_ids?: string[]; allowed_role_ids?: string[]; replied_user?: boolean }
export type Campaign = { id: string; owner_discord_user_id: DiscordSnowflake; logical_campaign_key: string; name: string; source_language_code: string; message_model: MessageModel; allowed_mentions_policy: AllowedMentionsPolicy; publication_mode: PublicationMode; attachment_policy: CampaignAttachmentPolicy; lifecycle_status: CampaignLifecycleStatus; version: number; created_at: string | null; updated_at: string | null }
export type CampaignTarget = { id: string; guild_id: DiscordSnowflake; campaign_id: string; target_kind: CampaignTargetKind; discord_channel_id: DiscordSnowflake | null; translation_group_id: string | null; translation_publication_mode: TranslationPublicationMode | null; selected_language_profile_ids: string[]; logical_group_id: string | null }
export type CampaignSchedule = { id: string; campaign_id: string; schedule_kind: ScheduleKind; fire_at: string | null; rrule: string | null; timezone: string | null; starts_at: string | null; misfire_policy: string; dst_nonexistent_policy: string; dst_ambiguous_policy: string; catch_up_bound: number; next_fire_at: string | null; version: number }
export type CampaignDelivery = { id: string; guild_id: DiscordSnowflake; campaign_id: string; occurrence_id: string; target_id: string; language_profile_id: string | null; delivery_key: string; discord_channel_id: DiscordSnowflake; status: DeliveryStatus; discord_message_id: string | null; attempt_count: number; last_error: string | null; created_at: string | null; updated_at: string | null }
export type CampaignSimulationDestination = { guild_id: DiscordSnowflake; discord_channel_id: DiscordSnowflake; language_profile_id: string | null; ready: boolean; blocked_reason: string | null; translation_state: string; delivery_executable: boolean }
export type CampaignMessageContentWarning = { trigger_id: string; available: boolean; is_blocking: boolean }
export type CampaignSimulationReport = { destinations: CampaignSimulationDestination[]; total_destinations: number; ready_destinations: number; blocked_destinations: number; estimated_delivery_count: number; blockers: Record<string, number>; message_content_warnings: CampaignMessageContentWarning[]; undeclared_template_variable_names: string[]; matched_glossary_terms: string[] }
export type ApprovedVariant = { id: string; campaign_id: string; target_language_code: string; source_fingerprint: string; localized_message_model: MessageModel; approved_by_discord_user_id: DiscordSnowflake; approved_at: string | null }
export type CampaignVariantPreview = { campaign_id: string; target_language_code: string; outcome: VariantOutcome; current_source_fingerprint: string; approved_variant: ApprovedVariant | null }
export type TemplateVariableType = 'TRANSLATABLE_TEXT'|'NON_TRANSLATABLE'|'LOCALIZED_VALUE'|'PROTECTED'
export type TemplateVariable = { id: string; campaign_id: string; name: string; variable_type: TemplateVariableType; value: string | null; values_by_language: Record<string, string> | null }
export type GlossaryScope = 'CAMPAIGN'|'GUILD'|'GLOBAL_USER'
export type GlossaryBehavior = 'DO_NOT_TRANSLATE'|'FORCED_TRANSLATION'
export type GlossaryMatchMode = 'EXACT'|'CASE_INSENSITIVE'
export type GlossaryEntry = { id: string; scope_kind: GlossaryScope; source_term: string; behavior: GlossaryBehavior; campaign_id: string | null; guild_id: string | null; target_language_code: string | null; forced_translation: string | null; match_mode: GlossaryMatchMode }
export type CampaignTrigger = { id: string; campaign_id: string; event_type: string; condition_ast: Record<string, unknown>; max_causation_depth: number; requires_message_content: boolean; version: number }
export type TriggerSourceScopeKind = 'GUILD'|'CHANNEL'|'CATEGORY'
export type TriggerSourceBinding = { id: string; guild_id: DiscordSnowflake; trigger_id: string; source_scope_kind: TriggerSourceScopeKind; discord_resource_id: string | null }
export type RetentionPolicy = { retention_days: number | null; min_retention_days: number; max_retention_days: number; purged_delivery_statuses: string[] }
