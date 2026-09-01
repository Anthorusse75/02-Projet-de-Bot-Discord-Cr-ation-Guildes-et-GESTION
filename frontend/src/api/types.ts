import type { DiscordSnowflake } from '../shared/discord-id'

export type ApiErrorEnvelope = { error: { code: string; message_key: string; params: Record<string, string | number>; request_id: string } }
export type Me = { authenticated: true; user: { discord_user_id: DiscordSnowflake; username: string; global_name: string | null }; active_guild_id: DiscordSnowflake | null; csrf_token: string; policy_version: number }
export type Guild = { guild_id: DiscordSnowflake; name: string; owner: boolean; permissions: string; installation_status: string | null }
export type Channel = { guild_id: DiscordSnowflake; id: DiscordSnowflake; type: number; name: string; position: number; parent_id: DiscordSnowflake | null; resource_kind: string; observability: string; freshness: string; data_assertion: string; threads?: Channel[] }
export type Structure = { guild_id: DiscordSnowflake; source: 'LOCAL_CACHE'; discord_rest_calls: 0; categories: Array<Channel & { channels: Channel[] }>; root_channels: Channel[] }
export type Role = { id: DiscordSnowflake; name: string; position: number; permissions: string; known_flags: string[]; unknown_bits: string; managed: boolean; freshness: string }
export type Roles = { guild_id: DiscordSnowflake; source: 'LOCAL_CACHE'; roles: Role[] }
export type Plan = { id: string; guild_id: DiscordSnowflake; status: string; state_version: number; plan_hash: string; risk_level: string; impact: Record<string, number>; reinforced_confirmation_required: boolean; created_at: string; updated_at: string; error_code: string | null }
export type AuditEvent = { id: string; event_type: string; target_type: string; target_id: string | null; result_state: string; occurred_at: string; plan_id: string | null; correlation_id: string }
export type PortableArtifact = { id: string; artifact_type: string; kind: string; name: string | null; content_hash: string; created_at: string; expires_at: string | null }
export type Template = { id: string; name: string; artifact_type: string; created_at: string; updated_at: string }
export type CapabilityOutcome = 'CAN' | 'CANNOT' | 'UNKNOWN'
export type CapabilityDecision = { outcome: CapabilityOutcome; causes: string[]; remediations: string[]; warnings?: string[]; scope_kind?: string; scope_id?: string }
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
export type LogicalGroup = { id: string; guild_id: DiscordSnowflake; name: string; slug: string; description: string | null }
export type ScheduleKind = 'IMMEDIATE'|'ONE_SHOT'|'RECURRING'
export type DeliveryStatus = 'PENDING'|'CLAIMED'|'SENDING'|'SENT'|'FAILED'|'UNKNOWN'|'INTERVENTION_REQUIRED'|'DELETED'
export type VariantOutcome = 'REUSABLE'|'STALE'|'MISSING'
export type MessageModel = { content: string; embeds: unknown[] }
export type AllowedMentionsPolicy = { allow_everyone?: boolean; allowed_user_ids?: string[]; allowed_role_ids?: string[]; replied_user?: boolean }
export type Campaign = { id: string; owner_discord_user_id: DiscordSnowflake; logical_campaign_key: string; name: string; source_language_code: string; message_model: MessageModel; allowed_mentions_policy: AllowedMentionsPolicy; publication_mode: PublicationMode; attachment_policy: CampaignAttachmentPolicy; lifecycle_status: CampaignLifecycleStatus; version: number; created_at: string | null; updated_at: string | null }
export type CampaignTarget = { id: string; guild_id: DiscordSnowflake; campaign_id: string; target_kind: CampaignTargetKind; discord_channel_id: DiscordSnowflake | null; translation_group_id: string | null; translation_publication_mode: TranslationPublicationMode | null; selected_language_profile_ids: string[]; logical_group_id: string | null }
export type CampaignSchedule = { id: string; campaign_id: string; schedule_kind: ScheduleKind; fire_at: string | null; rrule: string | null; timezone: string | null; starts_at: string | null; misfire_policy: string; dst_nonexistent_policy: string; dst_ambiguous_policy: string; catch_up_bound: number; next_fire_at: string | null; version: number }
export type CampaignDelivery = { id: string; guild_id: DiscordSnowflake; campaign_id: string; occurrence_id: string; target_id: string; language_profile_id: string | null; delivery_key: string; discord_channel_id: DiscordSnowflake; status: DeliveryStatus; discord_message_id: string | null; attempt_count: number; last_error: string | null; created_at: string | null; updated_at: string | null }
export type CampaignSimulationDestination = { guild_id: DiscordSnowflake; discord_channel_id: DiscordSnowflake; language_profile_id: string | null; ready: boolean; blocked_reason: string | null; translation_state: string; delivery_executable: boolean }
export type CampaignMessageContentWarning = { trigger_id: string; available: boolean; is_blocking: boolean }
export type CampaignSimulationReport = { destinations: CampaignSimulationDestination[]; total_destinations: number; ready_destinations: number; blocked_destinations: number; estimated_delivery_count: number; blockers: Record<string, number>; message_content_warnings: CampaignMessageContentWarning[] }
export type ApprovedVariant = { id: string; campaign_id: string; target_language_code: string; source_fingerprint: string; localized_message_model: MessageModel; approved_by_discord_user_id: DiscordSnowflake; approved_at: string | null }
export type CampaignVariantPreview = { campaign_id: string; target_language_code: string; outcome: VariantOutcome; current_source_fingerprint: string; approved_variant: ApprovedVariant | null }
