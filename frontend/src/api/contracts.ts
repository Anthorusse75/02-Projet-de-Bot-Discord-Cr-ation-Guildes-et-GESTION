import type { paths } from './openapi'

// These assignments are a compile-time drift gate for every endpoint consumed by STAGE 07.
export type MeResponse = paths['/api/v1/me']['get']['responses'][200]
export type GuildListResponse = paths['/api/v1/guilds']['get']['responses'][200]
export type StructureResponse = paths['/api/v1/guilds/{guild_id}/structure']['get']['responses'][200]
export type RoleResponse = paths['/api/v1/guilds/{guild_id}/roles']['get']['responses'][200]
export type PlanListResponse = paths['/api/v1/guilds/{guild_id}/plans']['get']['responses'][200]
export type AuditResponse = paths['/api/v1/guilds/{guild_id}/audit']['get']['responses'][200]
export type LocaleResponse = paths['/api/v1/ui/locales/{locale}/catalog/{catalog_version}']['get']['responses'][200]
