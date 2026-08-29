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
export type TranslationVariant = { id: string; language_profile_id: string; discord_category_id?: DiscordSnowflake; discord_channel_id?: DiscordSnowflake; state: string; translation_channel_group_id?: string; translation_category_variant_id?: string | null }
export type TranslationChannelGroup = { id: string; logical_key: string; display_name: string; source_language_profile_id: string | null }
export type TranslationRoute = { id: string; source_language_profile_id: string; destination_language_profile_id: string; state: string }
export type TranslationGroup = { id: string; guild_id: DiscordSnowflake; name: string; root_kind: string; routing_mode: string; visibility_scope_id: string | null; source_language_profile_id: string | null; provider_binding_id: string | null; status: string; version: number; languages: LanguageProfile[]; category_variants: TranslationVariant[]; channel_groups: TranslationChannelGroup[]; channel_variants: TranslationVariant[]; routes: TranslationRoute[] }
export type TranslationProviderBinding = { id: string; provider_type: string; status: string; capabilities_json: Record<string, unknown>; last_validated_at: string | null }
export type VisibilityBinding = { id: string; visibility_scope_id: string; language_profile_id: string; discord_role_id: DiscordSnowflake; state: string }
export type ResourceLanguagePolicy = { id: string; resource_type: 'CATEGORY'|'CHANNEL'; discord_resource_id: DiscordSnowflake; explicit_language_profile_id: string | null; inherit_language: boolean; visibility_policy: 'OPEN_ALL'|'LANGUAGE_FILTERED'|'SCOPE_AND_LANGUAGE'|'CUSTOM'; visibility_scope_id: string | null }
export type TranslationWorkspace = { guild_id: DiscordSnowflake; source: 'POSTGRESQL_DURABLE_TRUTH'; discord_rest_calls: 0; groups: TranslationGroup[]; providers: TranslationProviderBinding[]; visibility_bindings: VisibilityBinding[]; languages: LanguageProfile[]; resource_language_policies: ResourceLanguagePolicy[] }
