import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

const USER = '700000000000000003'
const GUILD = '700000000000000001'
const ROLE = '700000000000000011'
const OTHER_ROLE = '700000000000000012'
const CAT = '700000000000000101'
const CHANNEL = '700000000000000201'
const VOICE = '700000000000000202'
const MEMBER = '700000000000000301'
const BOT_DENIED = '700000000000000401'
const BOT_UNKNOWN = '700000000000000402'
const POLICY = '11111111-1111-4111-8111-111111111111'

type Harness = { policies: Record<string, unknown>[]; favorites?: string[]; requests: Array<{path:string;method:string;body:unknown}>; conflict?: boolean; denied?: boolean; family?: 'voice'|'mentions'|'bot'; drift?: 'DRIFT'|'UNKNOWN'|'COMPLIANT'; driftAccepted?: boolean }
const can = () => ({ outcome: 'CAN', causes: [], remediations: [] })

function capabilities(denied = false) {
  const userCapabilities: Record<string, ReturnType<typeof can>> = { 'tenant.read': can(), 'policies.create': can(), 'policies.update': can(), 'policies.activate': can(), 'policies.retire': can(), 'plans.create': can() }
  if (!denied) userCapabilities['policies.read'] = can()
  return { guild_id: GUILD, source: 'AUTHORIZATION_AND_LOCAL_CACHE', discord_rest_calls: 0,
    user_capabilities: userCapabilities,
    scoped_capabilities: { scope_kind: 'GUILD', scope_id: '*', capabilities: {} }, bot_operations: {}, coverage: 'FULL', completeness: 'FULL', freshness: 'FRESH' }
}

function roles() { return { guild_id: GUILD, source: 'LOCAL_CACHE', discord_rest_calls: 0, roles: [
  { id: ROLE, name: 'Managers', position: 5, permissions: '0', known_flags: [], unknown_bits: '0', managed: false, freshness: 'FRESH' },
  { id: OTHER_ROLE, name: 'Guests', position: 4, permissions: '0', known_flags: [], unknown_bits: '0', managed: false, freshness: 'FRESH' },
] } }

function structure() { const base = { guild_id: GUILD, position: 0, resource_kind: 'CHANNEL', observability: 'VISIBLE', freshness: 'FRESH', data_assertion: 'CURRENT_CONFIRMED', threads: [] }; return { guild_id: GUILD, source: 'LOCAL_CACHE', discord_rest_calls: 0, categories: [{ ...base, id: CAT, type: 4, name: 'Direction', parent_id: null, channels: [{ ...base, id: CHANNEL, type: 0, name: 'board', parent_id: CAT }, { ...base, id: VOICE, type: 2, name: 'briefing', parent_id: CAT }] }], root_channels: [] } }

function policy(overrides: Record<string, unknown> = {}) { return { policy_id: POLICY, guild_id: GUILD, policy_type: 'ACCESS_CONTROL', contract_version: 1, name: 'Board access', description: 'Managers only', lifecycle_state: 'DRAFT', revision: 1, priority: 0, locked: false, scope_type: 'CHANNEL', scope_id: CHANNEL, conditions: [{ kind: 'ROLE_MATCH', match: 'ANY', role_ids: [ROLE] }], effects: [{ kind: 'SET_ACCESS', access: 'VIEW', decision: 'ALLOW' }], metadata: { summary: 'Managers only', tags: ['did-native:visible_only', 'audience:include'], reason: null }, created_by_user_id: USER, modified_by_user_id: USER, created_at: '2026-09-15T08:00:00Z', updated_at: '2026-09-15T08:00:00Z', activated_at: null, disabled_at: null, retired_at: null, ...overrides } }

function resolution(outcome: 'CAN'|'CANNOT'|'BLOCKED'|'UNKNOWN', conflicts: Record<string, unknown>[] = [], access = 'VIEW', permissions = ['VIEW_CHANNEL'], inherited = false) { return { guild_id: GUILD, subject_id: MEMBER, decision: `ACCESS_CONTROL:${access}`, outcome, target_scope_type: 'CHANNEL', target_scope_id: CHANNEL, target_state: 'CURRENT', target_freshness: 'FRESH', coverage: 'FULL', applicable_policies: [{ policy_id: POLICY, revision: 1, priority: 0, scope_type: inherited ? 'GUILD' : 'CHANNEL', scope_id: inherited ? null : CHANNEL, inherited, specificity: inherited ? 0 : 3 }], contributions: [{ policy_id: POLICY, revision: 1, effect_index: 0, priority: 0, scope_type: inherited ? 'GUILD' : 'CHANNEL', scope_id: inherited ? null : CHANNEL, family: 'RESOURCE', specificity: inherited ? 0 : 3, inherited, access, decision: outcome === 'CAN' ? 'ALLOW' : 'DENY', condition_outcome: 'TRUE', selected: outcome === 'CAN' || outcome === 'CANNOT', disposition: outcome === 'BLOCKED' ? 'CONFLICT_UNRESOLVED' : 'SELECTED' }], conflicts, source_scopes: [{ policy_id: POLICY, revision: 1, scope_type: inherited ? 'GUILD' : 'CHANNEL', scope_id: inherited ? null : CHANNEL, family: 'RESOURCE', specificity: inherited ? 0 : 3, inherited }], priority_trace: [], conditions: [], incomplete_reasons: outcome === 'UNKNOWN' ? ['policy.member_roles_incomplete'] : [], warnings: [], source_versions: ['cache-v1'], discord_permissions: permissions, discord_allow_bits: outcome === 'CAN' ? '1' : '0', discord_deny_bits: outcome === 'CAN' ? '0' : '1', discord_translation_diagnostics: [] } }

function preview(conflict = false, family?: Harness['family']) {
  const blockedConflict = { policy_ids: [POLICY, '22222222-2222-4222-8222-222222222222'], revisions: [1, 2], source_scopes: [`CHANNEL:${CHANNEL}`, `ROLE:${OTHER_ROLE}`], effects: ['ALLOW VIEW', 'DENY VIEW'], resolution_rule: null, outcome: 'BLOCKED', winning_policy_ids: [] }
  const entries = conflict
    ? [{ target: { subject_id: MEMBER, scope_type: 'CHANNEL', scope_id: CHANNEL, requested_access: 'VIEW' }, current: resolution('CAN'), proposed: resolution('BLOCKED', [blockedConflict]), access_change: 'BLOCKED', gained_contributions: [], lost_contributions: [], conflicts_created: ['conflict'], conflicts_resolved: [], diagnostics: [], warnings: [], remediations: [] },
       { target: { subject_id: '700000000000000302', scope_type: 'CHANNEL', scope_id: CHANNEL, requested_access: 'VIEW' }, current: resolution('CANNOT'), proposed: resolution('UNKNOWN'), access_change: 'UNKNOWN', gained_contributions: [], lost_contributions: [], conflicts_created: [], conflicts_resolved: [], diagnostics: ['policy.member_roles_incomplete'], warnings: [], remediations: [] }]
    : [{ target: { subject_id: MEMBER, scope_type: 'CHANNEL', scope_id: family === 'voice' ? VOICE : CHANNEL, requested_access: family === 'voice' ? 'CONNECT' : family === 'mentions' ? 'MENTION_EVERYONE_HERE' : 'VIEW' }, current: resolution('CANNOT'), proposed: family === 'voice' ? resolution('CAN', [], 'CONNECT', ['CONNECT']) : family === 'mentions' ? resolution('CAN', [], 'MENTION_EVERYONE_HERE', ['MENTION_EVERYONE'], true) : resolution('CAN'), access_change: 'GAINED', gained_contributions: ['new'], lost_contributions: [], conflicts_created: [], conflicts_resolved: [], diagnostics: [], warnings: [], remediations: [] }]
  return { policy_id: POLICY, policy_revision: 1, lifecycle_state: 'DRAFT', scope_type: 'CHANNEL', scope_id: CHANNEL, entries, impact: { accuracy: 'EXACT', candidate_contexts: entries.length, evaluated_contexts: entries.length, affected_resources: 1, affected_roles: conflict ? 2 : 1, affected_members: entries.length, access_gains: conflict ? 0 : 1, access_losses: 0, conflicts: conflict ? 1 : 0, impossible_or_incomplete_targets: conflict ? 2 : 0, lower_bound_only: false, diagnostics: [] }, freshness: 'FRESH', coverage: 'FULL', source_versions: ['cache-v1'], warnings: [], persisted: false, discord_mutations: 0 }
}

function driftPreview(mode: NonNullable<Harness['drift']>, accepted = false) {
  const unknown = mode === 'UNKNOWN'
  const changed = mode !== 'COMPLIANT'
  const entry = { target: { subject_id: MEMBER, scope_type: 'CHANNEL', scope_id: CHANNEL, requested_access: 'VIEW' }, current: resolution(unknown ? 'UNKNOWN' : changed ? 'CANNOT' : 'CAN'), proposed: resolution('CAN'), access_change: unknown ? 'UNKNOWN' : changed ? 'GAINED' : 'UNCHANGED', gained_contributions: changed ? ['policy'] : [], lost_contributions: [], conflicts_created: [], conflicts_resolved: [], diagnostics: unknown ? ['policy.drift.discord_state_unknown'] : [], warnings: [], remediations: [] }
  return { policy_id: POLICY, policy_revision: 3, lifecycle_state: 'ACTIVE', scope_type: 'CHANNEL', scope_id: CHANNEL, entries: [entry], impact: { accuracy: unknown ? 'INCOMPLETE' : 'EXACT', candidate_contexts: 1, evaluated_contexts: 1, affected_resources: changed ? 1 : 0, affected_roles: 0, affected_members: changed ? 1 : 0, access_gains: changed ? 1 : 0, access_losses: 0, conflicts: 0, impossible_or_incomplete_targets: unknown ? 1 : 0, lower_bound_only: unknown, diagnostics: unknown ? ['policy.drift.member_coverage_incomplete'] : [] }, freshness: unknown ? 'STALE' : 'FRESH', coverage: unknown ? 'DEGRADED' : 'FULL', source_versions: ['cache-v2'], warnings: accepted ? ['policy.drift.exception_accepted'] : [], persisted: false, discord_mutations: 0 }
}

async function install(page: Page, harness: Harness) {
  await page.route('**/health/features', (route) => route.fulfill({ json: { features: { oauth: true, live_events: true, portability: true } } }))
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request(); const path = new URL(request.url()).pathname; const method = request.method(); const body = request.postDataJSON() ?? null
    if (!['GET', 'HEAD'].includes(method)) harness.requests.push({ path, method, body })
    if (path === '/api/v1/ui/locales') return route.fulfill({ json: { catalog_version: 'did-ui-v2', locales: [] } })
    if (path.startsWith('/api/v1/ui/locales/')) return route.fulfill({ status: 404, json: {} })
    if (path === '/api/v1/me') return route.fulfill({ json: { authenticated: true, user: { discord_user_id: USER, username: 'owner', global_name: 'Owner' }, active_guild_id: GUILD, csrf_token: 'csrf', policy_version: 1 } })
    if (path === '/api/v1/me/preferences') return route.fulfill({ json: { ui_locale_override_code: 'en', timezone: null } })
    if (path === '/api/v1/guilds') return route.fulfill({ json: { guilds: [{ guild_id: GUILD, name: 'Guild A', owner: true, permissions: '8', installation_status: 'ACTIVE' }] } })
    if (path.endsWith('/dashboard-capabilities')) return route.fulfill({ json: capabilities(harness.denied) })
    if (path.endsWith('/roles')) return route.fulfill({ json: roles() })
    if (path.endsWith('/structure')) return route.fulfill({ json: structure() })
    if (path.endsWith('/logical-groups')) return route.fulfill({ json: { guild_id: GUILD, groups: [] } })
    if (path.endsWith('/policy-favorites') && method === 'GET') return route.fulfill({ json: { guild_id: GUILD, favorite_keys: harness.favorites ?? [] } })
    if (path.endsWith('/policy-favorites') && method === 'PATCH') {
      const update = body as { favorite_key:string; pinned:boolean }
      const favorites = new Set(harness.favorites ?? [])
      if (update.pinned) favorites.add(update.favorite_key); else favorites.delete(update.favorite_key)
      harness.favorites = [...favorites]
      return route.fulfill({ json: { guild_id: GUILD, favorite_keys: harness.favorites } })
    }
    if (path.endsWith('/policies') && method === 'GET') return route.fulfill({ json: { guild_id: GUILD, policies: harness.policies } })
    if (path.endsWith('/policies') && method === 'POST') { const created = policy({ ...(body as Record<string, unknown>), policy_id: harness.policies.length ? '66666666-6666-4666-8666-666666666666' : POLICY }); harness.policies.push(created); return route.fulfill({ status: 201, json: created }) }
    if (path.endsWith(`/policies/${POLICY}/drift-preview`)) return route.fulfill({ json: driftPreview(harness.drift ?? 'COMPLIANT', harness.driftAccepted) })
    if (path.endsWith(`/policies/${POLICY}/lock`) || path.endsWith(`/policies/${POLICY}/unlock`)) { const locked = path.endsWith('/lock'); const current = harness.policies[0]; const updated = { ...current, locked, revision: Number(current.revision) + 1 }; harness.policies[0] = updated; return route.fulfill({ json: updated }) }
    if (path.endsWith(`/policies/${POLICY}/accept-drift`)) { harness.driftAccepted = true; const current = harness.policies[0]; const metadata = current.metadata as { summary:string; tags:string[]; reason:null }; const updated = { ...current, revision: Number(current.revision) + 1, metadata: { ...metadata, tags: [...metadata.tags, 'drift-exception:test'] } }; harness.policies[0] = updated; return route.fulfill({ json: updated }) }
    if (path.endsWith(`/policies/${POLICY}/drift-plan`)) return route.fulfill({ status: 201, json: { created: true, preview: driftPreview('DRIFT'), plan: { id: '55555555-5555-4555-8555-555555555555', status: 'VALIDATED', state_version: 2 }, preflight: { allowed: true, errors: [], warnings: [] } } })
    if (path.endsWith(`/policies/${POLICY}/deletion-preview`)) return route.fulfill({ json: { policy: harness.policies[0], plans: [{ id: '55555555-5555-4555-8555-555555555555', source_policy_revision: 3, status: 'SUCCEEDED', created_at: '2026-09-15T09:00:00Z' }], referencing_policies: [{ policy_id: '22222222-2222-4222-8222-222222222222', name: 'Derived board rule', lifecycle_state: 'DRAFT', reference_kinds: ['SOURCE'] }], bulk_operation_ids: ['bulk-operation:test'], scope_binding_count: 1, available_replacements: [], access_impact: { ...driftPreview('DRIFT'), impact: { ...driftPreview('DRIFT').impact, access_gains: 0, access_losses: 1 } }, discord_mutations: 0, selected_replacement_valid: true, strategies: [{ strategy: 'DETACH', available: true, requires_plan: false }, { strategy: 'REPLACE', available: false, requires_plan: true }, { strategy: 'DELETE_BINDINGS', available: true, requires_plan: true }] } })
    if (path.endsWith(`/policies/${POLICY}/disable-plan`)) return route.fulfill({ status: 201, json: { created: true, preview: driftPreview('DRIFT'), plan: { id: '77777777-7777-4777-8777-777777777777', status: 'VALIDATED', state_version: 2 }, preflight: { allowed: true, errors: [], warnings: [] } } })
    if (path.endsWith(`/policies/${POLICY}/delete`)) { const current = harness.policies[0]; const updated = { ...current, lifecycle_state: 'RETIRED', locked: false, revision: Number(current.revision) + 1 }; harness.policies[0] = updated; return route.fulfill({ json: { ...updated, deletion: { strategy: (body as {strategy:string}).strategy, history_preserved: true, discord_mutations: 0 } } }) }
    if (/\/policies\/[^/]+\/preview$/.test(path)) return route.fulfill({ json: preview(Boolean(harness.conflict), harness.family) })
    if (path.endsWith(`/policies/${POLICY}/versions`)) return route.fulfill({ json: { guild_id: GUILD, policy_id: POLICY, versions: [{ version_id: '33333333-3333-4333-8333-333333333333', guild_id: GUILD, policy_id: POLICY, revision: 1, change_kind: 'CREATE', snapshot: policy(), author_user_id: USER, correlation_id: '44444444-4444-4444-8444-444444444444', idempotency_key: null, created_at: '2026-09-15T08:00:00Z' }] } })
    if (path.endsWith('/bots/audit')) return route.fulfill({ json: { bots: [{ user_id: BOT_DENIED, status: 'ACTIVE', incomplete_reasons: [] }, { user_id: BOT_UNKNOWN, status: 'STALE', incomplete_reasons: ['cache.stale'] }] } })
    if (path.includes('/bots/') && path.endsWith('/access-map')) { const unknown = path.includes(BOT_UNKNOWN); return route.fulfill({ json: { channels: [{ channel_id: CHANNEL, status: 'VISIBLE', minimum: { functions: ['READ', 'WRITE', 'THREADS'], outcome: unknown ? 'UNKNOWN' : 'CANNOT', required_permissions: ['VIEW_CHANNEL', 'READ_MESSAGE_HISTORY', 'SEND_MESSAGES', 'CREATE_PUBLIC_THREADS', 'CREATE_PRIVATE_THREADS', 'SEND_MESSAGES_IN_THREADS'], missing_permissions: unknown ? [] : ['SEND_MESSAGES', 'CREATE_PUBLIC_THREADS'], causes: [unknown ? 'capability.cache.stale' : 'capability.permission_missing.SEND_MESSAGES'], remediations: [unknown ? 'capability.refresh_required' : 'capability.grant_minimum_permissions'], warnings: [] } }] } }) }
    if (path.endsWith('/policy-resolution')) {
      if (harness.conflict) {
        const conflict = { policy_ids: [POLICY, '22222222-2222-4222-8222-222222222222'], revisions: [1, 2], source_scopes: [`CHANNEL:${CHANNEL}`, `ROLE:${OTHER_ROLE}`], effects: ['ALLOW VIEW', 'DENY VIEW'], resolution_rule: null, outcome: 'BLOCKED', winning_policy_ids: [] }
        return route.fulfill({ json: { ...resolution('BLOCKED', [conflict]), conflict_explanations: [{ conflict, accepted: false, causing_roles: [{ role_id: ROLE, source_policy_id: POLICY, source: 'CONDITION' }, { role_id: OTHER_ROLE, source_policy_id: '22222222-2222-4222-8222-222222222222', source: 'CONDITION' }], reason_key: 'policy.conflict.blocked', remediations: [{ kind: 'REMOVE_MEMBER_ROLE', target_id: ROLE, route: 'roles', requires_separate_plan: true, collateral_losses: ['MANAGE_CHANNELS', 'VIEW_CHANNEL'], collateral_scope: [CHANNEL], reason_key: 'policy.conflict.remediation.remove_role' }, { kind: 'EDIT_POLICY_DRAFT', target_id: POLICY, route: 'policies', requires_separate_plan: true, collateral_losses: [], collateral_scope: [POLICY], reason_key: 'policy.conflict.remediation.edit_policy_draft' }] }], blacklist_regrants: [], observable_access_conflict: null } })
      }
      return route.fulfill({ json: harness.family === 'mentions' ? resolution('CAN', [], 'MENTION_EVERYONE_HERE', ['MENTION_EVERYONE'], true) : resolution('CAN') })
    }
    if (/\/policies\/[^/]+\/plan$/.test(path)) return route.fulfill({ status: 201, json: { created: true, preview: preview(false, harness.family), plan: { id: '55555555-5555-4555-8555-555555555555', status: 'VALIDATED', state_version: 2 }, preflight: { allowed: true, errors: [], warnings: [] } } })
    if (path.endsWith('/plans')) return route.fulfill({ json: { guild_id: GUILD, plans: [] } })
    return route.fulfill({ status: 404, json: {} })
  })
}

test('@a11y creates a DRAFT from a native human intention, previews canonically and prepares Policy→Plan without APPLY', async ({ page }) => {
  const harness: Harness = { policies: [], requests: [] }; await install(page, harness)
  await page.goto(`/guild/${GUILD}/policies`)
  await expect(page.getByRole('heading', { name: 'Access policies' })).toBeVisible()
  await page.getByLabel('Target resource').selectOption(`TEXT_CHANNEL:${CHANNEL}`)
  await page.getByRole('button', { name: /^Visible only to/ }).click()
  await page.getByRole('group', { name: 'Roles and audiences' }).getByText('Managers').click()
  await page.getByRole('group', { name: 'Roles and audiences' }).getByText('Guests').click()
  await page.getByLabel('Policy name').fill('Board access')
  await page.getByRole('tab', { name: 'Expert mode' }).click()
  await expect(page.getByText(new RegExp(OTHER_ROLE))).toBeVisible()
  await page.getByRole('tab', { name: 'Simple mode' }).click()
  await expect(page.getByRole('group', { name: 'Roles and audiences' }).getByLabel('Guests')).toBeChecked()
  await page.getByRole('button', { name: 'Create draft' }).click()
  await expect(page.getByText('Draft created. Discord was not changed.')).toBeVisible()
  await page.getByRole('button', { name: 'Preview impact' }).click()
  await expect(page.getByText('Exact impact')).toBeVisible()
  await expect(page.getByText('Current: Denied · Proposed: Allowed')).toBeVisible()
  await page.getByRole('tab', { name: 'Expert mode' }).click()
  await expect(page.getByText(POLICY, { exact: true })).toBeVisible()
  await expect(page.getByText(/INCLUDE/)).toBeVisible()
  await expect(page.getByText(new RegExp(ROLE))).toBeVisible()
  const accessibility = await new AxeBuilder({ page }).include('#main').analyze()
  expect(accessibility.violations.filter((item) => ['serious', 'critical'].includes(item.impact ?? ''))).toEqual([])
  await page.getByRole('button', { name: 'Prepare plan' }).click()
  await expect(page).toHaveURL(new RegExp(`/guild/${GUILD}/plans$`))
  expect(harness.requests.some((item) => item.path.endsWith(`/policies/${POLICY}/plan`))).toBe(true)
  expect(harness.requests.some((item) => /apply/i.test(item.path))).toBe(false)
})

test('shows multi-role conflict causes, BLOCKED/UNKNOWN outcomes, explain and safe revision reuse', async ({ page }) => {
  const harness: Harness = { policies: [policy()], requests: [], conflict: true }; await install(page, harness)
  await page.goto(`/guild/${GUILD}/policies`)
  await page.getByLabel('Target resource').selectOption(`TEXT_CHANNEL:${CHANNEL}`)
  await page.getByRole('button', { name: /^Board access/ }).click()
  await page.getByRole('button', { name: 'Preview impact' }).click()
  await expect(page.getByText('Blocked', { exact: true })).toBeVisible()
  await expect(page.getByText('Unknown', { exact: true })).toBeVisible()
  await expect(page.getByText(/Exception for member/)).toBeVisible()
  await page.getByRole('button', { name: 'Resolve this conflict' }).click()
  await expect(page.getByText(/load only validated remediations/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Prepare plan' })).toBeDisabled()
  await page.getByRole('button', { name: 'Why this result?' }).first().click()
  await expect(page.getByText('Why is this access allowed or denied?')).toBeVisible()
  await expect(page.getByText(/Granted through role\(s\): Managers, Guests/)).toBeVisible()
  await expect(page.getByText(/MANAGE_CHANNELS, VIEW_CHANNEL/)).toBeVisible()
  await expect(page.getByText(/separate Plan/).first()).toBeVisible()
  await page.getByRole('button', { name: 'History' }).click()
  await page.getByRole('button', { name: 'Create a new draft from this revision' }).click()
  expect(harness.requests.filter((item) => item.path.endsWith('/policies') && item.method === 'POST')).toHaveLength(1)
})

test('refuses the policy workspace when policies.read capability is missing', async ({ page }) => {
  const harness: Harness = { policies: [], requests: [], denied: true }; await install(page, harness)
  await page.goto(`/guild/${GUILD}/policies`)
  await expect(page.getByRole('alert')).toContainText('does not allow access to policies')
  await expect(page.getByRole('button', { name: 'Create draft' })).toHaveCount(0)
})

test('preselects the exact policy target provided by the Structure action', async ({ page }) => {
  const harness: Harness = { policies: [], requests: [] }; await install(page, harness)
  await page.goto(`/guild/${GUILD}/policies?targetType=CHANNEL&targetId=${CHANNEL}`)
  await expect(page.getByLabel('Target resource')).toHaveValue(`TEXT_CHANNEL:${CHANNEL}`)
})

test('@a11y pins a Policy per Guild and keeps it first after reload without APPLY', async ({ page }) => {
  const harness: Harness = { policies: [policy()], favorites: [], requests: [] }; await install(page, harness)
  await page.goto(`/guild/${GUILD}/policies?targetType=CHANNEL&targetId=${CHANNEL}`)

  await page.getByRole('button', { name: 'Pin Board access' }).click()
  const favorites = page.locator('.policy-favorites')
  await expect(favorites.getByRole('heading', { name: 'Favorites' })).toBeVisible()
  await expect(favorites.getByText('Board access', { exact: true })).toBeVisible()
  await expect(page.locator('.policy-catalog-panel > section').first()).toHaveClass(/policy-favorites/)

  await page.reload()
  await expect(page.getByRole('button', { name: 'Remove Board access from favorites' })).toBeVisible()
  expect(harness.favorites).toEqual([`custom:${POLICY}`])
  expect(harness.requests.filter((item) => item.path.endsWith('/policy-favorites') && item.method === 'PATCH')).toHaveLength(1)
  expect(harness.requests.some((item) => /apply/i.test(item.path))).toBe(false)
  const accessibility = await new AxeBuilder({ page }).include('.policy-catalog-panel').analyze()
  expect(accessibility.violations.filter((item) => ['serious', 'critical'].includes(item.impact ?? ''))).toEqual([])
})

test('@families private voice selects roles, previews Discord details and prepares a Plan', async ({ page }) => {
  const harness: Harness = { policies: [], requests: [], family: 'voice' }; await install(page, harness)
  await page.goto(`/guild/${GUILD}/policies`)
  await page.getByLabel('Target resource').selectOption(`VOICE_CHANNEL:${VOICE}`)
  await page.getByRole('button', { name: /^Private voice channel/ }).click()
  await page.getByRole('group', { name: 'Roles and audiences' }).getByText('Managers').click()
  await page.getByRole('button', { name: 'Create draft' }).click()
  await page.getByRole('button', { name: 'Preview impact' }).click()
  await expect(page.getByText('Join', { exact: true }).first()).toBeVisible()
  await page.getByText('Discord details', { exact: true }).click()
  await expect(page.getByText('CONNECT', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Prepare plan' }).click()
  await expect(page).toHaveURL(new RegExp(`/guild/${GUILD}/plans$`))
})

test('@families mention policy shows a Guild default and inherited channel exception', async ({ page }) => {
  const harness: Harness = { policies: [], requests: [], family: 'mentions' }; await install(page, harness)
  await page.goto(`/guild/${GUILD}/policies`)
  await page.getByRole('button', { name: /^Mention policy/ }).click()
  await page.getByText('Nobody', { exact: true }).click()
  await page.getByRole('button', { name: 'Create draft' }).click()
  await page.getByLabel('Target resource').selectOption(`TEXT_CHANNEL:${CHANNEL}`)
  await page.getByRole('button', { name: /^Mention policy/ }).click()
  await page.getByText('Everyone', { exact: true }).click()
  await page.getByRole('button', { name: 'Create draft' }).click()
  await page.getByRole('button', { name: 'Preview impact' }).click()
  await expect(page.getByText('Mention @everyone / @here', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Why this result?' }).click()
  await expect(page.getByText('Inherited from', { exact: true })).toBeVisible()
  await expect(page.getByText('Mention policy', { exact: true }).first()).toBeVisible()
})

test('@families minimal bot access explains CANNOT and UNKNOWN before preparing a Plan', async ({ page }) => {
  const harness: Harness = { policies: [], requests: [], family: 'bot' }; await install(page, harness)
  await page.goto(`/guild/${GUILD}/policies`)
  await page.getByLabel('Target resource').selectOption(`TEXT_CHANNEL:${CHANNEL}`)
  await page.getByRole('button', { name: /^Minimum bot access/ }).click()
  const botSelect = page.getByRole('combobox', { name: /Observed bot/ })
  await botSelect.selectOption(BOT_DENIED)
  await page.getByRole('group', { name: 'Required functions' }).getByText('Write', { exact: true }).click()
  await page.getByRole('group', { name: 'Required functions' }).getByText('Threads', { exact: true }).click()
  await expect(page.getByText('Denied', { exact: true })).toBeVisible()
  await expect(page.getByText(/Missing permissions: SEND_MESSAGES/)).toBeVisible()
  await expect(page.getByText(/Grant only the listed permissions/)).toBeVisible()
  await botSelect.selectOption(BOT_UNKNOWN)
  await expect(page.getByText('Unknown', { exact: true })).toBeVisible()
  await expect(page.getByText(/cached Discord data is incomplete or stale/)).toBeVisible()
  await botSelect.selectOption(BOT_DENIED)
  await page.getByRole('button', { name: 'Create draft' }).click()
  await page.getByRole('button', { name: 'Preview impact' }).click()
  await page.getByRole('button', { name: 'Prepare plan' }).click()
  await expect(page).toHaveURL(new RegExp(`/guild/${GUILD}/plans$`))
})

test('@a11y locked Policy UI shows drift cause and persists lock/unlock/accepted exception actions', async ({ page }) => {
  const harness: Harness = { policies: [policy({ lifecycle_state: 'ACTIVE', revision: 3, activated_at: '2026-09-15T09:00:00Z' })], requests: [], drift: 'DRIFT' }
  await install(page, harness)
  await page.goto(`/guild/${GUILD}/policies`)
  await page.getByLabel('Target resource').selectOption(`TEXT_CHANNEL:${CHANNEL}`)
  await page.getByRole('button', { name: /^Board access/ }).click()
  await expect(page.getByRole('heading', { name: 'A Discord change no longer matches' })).toBeVisible()
  await expect(page.getByText(/Discord is Denied, policy expects Allowed/)).toBeVisible()
  await expect(page.getByText('allow=1 · deny=0')).toBeHidden()

  await page.getByRole('button', { name: 'Lock policy' }).click()
  await expect(page.getByText('Policy locked. Future external drift is repaired automatically through the Plan worker.')).toBeVisible()
  await expect(page.getByText('Locked', { exact: true }).first()).toBeVisible()
  const automaticRepairHeading = page.getByRole('heading', { name: 'Automatic repair in progress' })
  await expect(automaticRepairHeading).toBeVisible()

  await page.getByRole('button', { name: 'Unlock policy' }).click()
  await page.getByRole('button', { name: 'Accept this exception' }).click()
  await expect(page.getByText('This exact exception was documented; Discord was not changed.')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Documented exception' })).toBeVisible()
  const accessibility = await new AxeBuilder({ page }).include('#main').analyze()
  expect(accessibility.violations.filter((item) => ['serious', 'critical'].includes(item.impact ?? ''))).toEqual([])
})

test('unlocked drift Repair creates only a canonical Plan and opens Plans', async ({ page }) => {
  const harness: Harness = { policies: [policy({ lifecycle_state: 'ACTIVE', revision: 3, activated_at: '2026-09-15T09:00:00Z' })], requests: [], drift: 'DRIFT' }
  await install(page, harness)
  await page.goto(`/guild/${GUILD}/policies`)
  await page.getByLabel('Target resource').selectOption(`TEXT_CHANNEL:${CHANNEL}`)
  await page.getByRole('button', { name: /^Board access/ }).click()
  await page.getByRole('button', { name: 'Repair with a Plan' }).click()
  await expect(page).toHaveURL(new RegExp(`/guild/${GUILD}/plans$`))
  expect(harness.requests.some((item) => item.path.endsWith(`/policies/${POLICY}/drift-plan`))).toBe(true)
  expect(harness.requests.some((item) => /apply/i.test(item.path))).toBe(false)
})

test('locked Policy with incomplete data is actionable Intervention required, never Compliant', async ({ page }) => {
  const harness: Harness = { policies: [policy({ lifecycle_state: 'ACTIVE', revision: 3, locked: true, activated_at: '2026-09-15T09:00:00Z', metadata: { summary: 'Managers only', tags: ['did-native:visible_only', 'reconciler:intervention_required'], reason: null } })], requests: [], drift: 'UNKNOWN' }
  await install(page, harness)
  await page.goto(`/guild/${GUILD}/policies`)
  await page.getByLabel('Target resource').selectOption(`TEXT_CHANNEL:${CHANNEL}`)
  await page.getByRole('button', { name: /^Board access/ }).click()
  await expect(page.getByRole('heading', { name: 'Intervention required' })).toBeVisible()
  await expect(page.getByText(/cannot safely prove or apply/)).toBeVisible()
  await expect(page.getByText('Compliant', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Repair with a Plan' })).toHaveCount(0)
})

test('@a11y deletion lists dependencies and prepares a separate binding-removal Plan without APPLY', async ({ page }) => {
  const harness: Harness = { policies: [policy({ lifecycle_state: 'ACTIVE', revision: 3, activated_at: '2026-09-15T09:00:00Z' })], requests: [], drift: 'COMPLIANT' }
  await install(page, harness)
  await page.goto(`/guild/${GUILD}/policies`)
  await page.getByLabel('Target resource').selectOption(`TEXT_CHANNEL:${CHANNEL}`)
  await page.getByRole('button', { name: /^Board access/ }).click()
  await page.getByRole('button', { name: 'Delete' }).click()
  const dialog = page.getByRole('dialog', { name: /Delete “Board access”/ })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByText('Historical Plans', { exact: true })).toBeVisible()
  await expect(dialog.getByText(/Derived board rule references this policy/)).toBeVisible()
  await expect(dialog.getByText(/immutable evidence/)).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  await dialog.getByText('Remove managed bindings', { exact: true }).click()
  await expect(dialog.getByText(/separate previewable Plan/)).toBeVisible()
  const accessibility = await new AxeBuilder({ page }).include('.policy-delete-dialog').analyze()
  expect(accessibility.violations.filter((item) => ['serious', 'critical'].includes(item.impact ?? ''))).toEqual([])
  await dialog.getByRole('button', { name: 'Confirm deletion strategy' }).click()
  await expect(page).toHaveURL(new RegExp(`/guild/${GUILD}/plans$`))
  expect(harness.requests.some((item) => item.path.endsWith(`/policies/${POLICY}/disable-plan`))).toBe(true)
  expect(harness.requests.some((item) => item.path.endsWith(`/policies/${POLICY}/delete`) && (item.body as {strategy:string}).strategy === 'DELETE_BINDINGS')).toBe(true)
  expect(harness.requests.some((item) => /apply/i.test(item.path))).toBe(false)
})
