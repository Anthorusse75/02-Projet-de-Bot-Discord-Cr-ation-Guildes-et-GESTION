from __future__ import annotations

from did.domain.discord_runtime import CoverageMode, FreshnessState, ObservabilityState
from did.domain.read_model import ChannelSnapshot, GuildSnapshot, MemberSnapshot
from did.domain.read_model.models import ChannelType
from did.permissions.models import (
    DecisionStatus,
    ImplicitDenial,
    PermissionDecision,
    PermissionOutcome,
    PermissionTraceEntry,
    TraceStep,
)
from did.permissions.registry import (
    DEFAULT_PERMISSION_REGISTRY,
    ChannelApplicability,
    PermissionRegistry,
)


class PermissionEvaluator:
    """Pure Discord permission evaluator; it has no transport or persistence dependency."""

    def __init__(self, registry: PermissionRegistry = DEFAULT_PERMISSION_REGISTRY) -> None:
        self.registry = registry

    def evaluate(
        self,
        *,
        guild: GuildSnapshot,
        member: MemberSnapshot,
        resource: ChannelSnapshot | None = None,
        parent: ChannelSnapshot | None = None,
        requested_permission: str | None = None,
    ) -> PermissionDecision:
        self._validate_tenant(guild, member, resource, parent)
        requested_bit = (
            self.registry.value(requested_permission) if requested_permission is not None else None
        )
        trace: list[PermissionTraceEntry] = []
        warnings: list[str] = []
        incomplete: list[str] = []
        unknown_status = False

        if guild.coverage.mode is not CoverageMode.FULL:
            incomplete.append("coverage.guild_not_full")
        if guild.coverage.freshness in {FreshnessState.STALE, FreshnessState.UNKNOWN}:
            incomplete.append("coverage.guild_not_current")
        if not guild.roles_complete or not member.roles_complete:
            incomplete.append("coverage.member_roles_incomplete")
        if member.freshness.state in {FreshnessState.STALE, FreshnessState.UNKNOWN}:
            incomplete.append("coverage.member_roles_not_current")

        everyone = guild.role(guild.guild_id)
        if everyone is None:
            incomplete.append("permissions.everyone_role_missing")
            unknown_status = True
            permissions = 0
        else:
            permissions = everyone.permissions
            trace.append(
                self._trace(
                    TraceStep.BASE_EVERYONE,
                    "ROLE",
                    everyone.role_id,
                    everyone.permissions,
                    0,
                    0,
                    permissions,
                    "permissions.trace.baseEveryone",
                )
            )

        observed_unknown = self.registry.unknown_bits(permissions)
        role_ids = sorted(set(member.role_ids) - {guild.guild_id})
        for role_id in role_ids:
            role = guild.role(role_id)
            if role is None:
                incomplete.append("permissions.member_role_unknown")
                continue
            before = permissions
            permissions |= role.permissions
            observed_unknown |= self.registry.unknown_bits(role.permissions)
            trace.append(
                self._trace(
                    TraceStep.BASE_ROLE,
                    "ROLE",
                    role.role_id,
                    role.permissions,
                    0,
                    before,
                    permissions,
                    "permissions.trace.baseRole",
                )
            )
        trace.append(
            self._trace(
                TraceStep.BASE_ROLES_OR,
                "ROLE_SET",
                None,
                permissions,
                0,
                permissions,
                permissions,
                "permissions.trace.baseRolesOr",
            )
        )

        bypass = False
        if member.user_id == guild.owner_id:
            before = permissions
            permissions = self.registry.known_mask | observed_unknown
            trace.append(
                self._trace(
                    TraceStep.OWNER_BYPASS,
                    "GUILD_OWNER",
                    member.user_id,
                    self.registry.known_mask,
                    0,
                    before,
                    permissions,
                    "permissions.trace.ownerBypass",
                )
            )
            bypass = True
        elif permissions & self.registry.value("ADMINISTRATOR"):
            before = permissions
            permissions = self.registry.known_mask | observed_unknown
            trace.append(
                self._trace(
                    TraceStep.ADMINISTRATOR_BYPASS,
                    "BASE_PERMISSIONS",
                    None,
                    self.registry.known_mask,
                    0,
                    before,
                    permissions,
                    "permissions.trace.administratorBypass",
                )
            )
            warnings.append("permissions.warning.administratorBypassesOverwrites")
            bypass = True

        permission_resource = resource
        if resource is not None and self._channel_applicability(resource.channel_type) is None:
            incomplete.append("permissions.channel_type_unknown")
            unknown_status = True
        if resource is not None and resource.is_thread:
            if not guild.coverage.threads_complete:
                incomplete.append("coverage.threads_incomplete")
            if parent is None or resource.parent_id != parent.channel_id:
                incomplete.append("permissions.thread_parent_missing")
                unknown_status = True
                permission_resource = None
            else:
                permission_resource = parent
                trace.append(
                    self._trace(
                        TraceStep.THREAD_INHERITANCE,
                        "PARENT_CHANNEL",
                        parent.channel_id,
                        0,
                        0,
                        permissions,
                        permissions,
                        "permissions.trace.threadInheritance",
                    )
                )

        if permission_resource is not None:
            if permission_resource.observability in {
                ObservabilityState.OBFUSCATED,
                ObservabilityState.ACCESS_LOST,
                ObservabilityState.UNKNOWN,
            }:
                incomplete.append("permissions.resource_not_currently_observable")
            if permission_resource.freshness.state in {
                FreshnessState.STALE,
                FreshnessState.UNKNOWN,
            }:
                incomplete.append("permissions.resource_stale")
            if not permission_resource.overwrites_complete:
                incomplete.append("permissions.overwrites_incomplete")
            if not bypass:
                permissions = self._apply_overwrites(
                    permissions,
                    guild_id=guild.guild_id,
                    member=member,
                    channel=permission_resource,
                    trace=trace,
                )

        calculated = permissions
        effective, implicit_denials = self._apply_implicit_permissions(
            calculated,
            resource=resource,
            member=member,
            incomplete=incomplete,
            warnings=warnings,
            trace=trace,
        )
        status = (
            DecisionStatus.UNKNOWN
            if unknown_status
            else DecisionStatus.INCOMPLETE
            if incomplete
            else DecisionStatus.COMPLETE
        )
        if incomplete:
            trace.append(
                self._trace(
                    TraceStep.COVERAGE_INCOMPLETE,
                    "COVERAGE",
                    None,
                    0,
                    0,
                    effective,
                    effective,
                    "permissions.trace.coverageIncomplete",
                )
            )
        if requested_bit is None:
            outcome = PermissionOutcome.UNKNOWN
        elif status is not DecisionStatus.COMPLETE:
            outcome = PermissionOutcome.UNKNOWN
        elif effective & requested_bit:
            outcome = PermissionOutcome.ALLOWED
        else:
            outcome = PermissionOutcome.DENIED
        data_assertion = (
            "LAST_KNOWN"
            if resource is not None
            and (
                resource.observability is not ObservabilityState.VISIBLE
                or resource.freshness.state is not FreshnessState.FRESH
            )
            else "CURRENT_CONFIRMED"
        )
        return PermissionDecision(
            guild_id=guild.guild_id,
            subject_id=member.user_id,
            resource_id=resource.channel_id if resource is not None else None,
            calculated_bits=calculated,
            effective_bits=effective,
            unknown_bits=self.registry.unknown_bits(calculated),
            status=status,
            requested_permission=requested_permission,
            outcome=outcome,
            coverage=guild.coverage.mode,
            freshness=(resource.freshness.state if resource else guild.coverage.freshness),
            incomplete_reasons=tuple(dict.fromkeys(incomplete)),
            trace=tuple(trace),
            implicit_denials=tuple(implicit_denials),
            warnings=tuple(dict.fromkeys(warnings)),
            source_versions=guild.source_versions,
            registry_version=self.registry.version,
            data_assertion=data_assertion,
        )

    def _apply_overwrites(
        self,
        permissions: int,
        *,
        guild_id: int,
        member: MemberSnapshot,
        channel: ChannelSnapshot,
        trace: list[PermissionTraceEntry],
    ) -> int:
        everyone = next(
            (
                overwrite
                for overwrite in channel.overwrites
                if overwrite.target_type == 0 and overwrite.target_id == guild_id
            ),
            None,
        )
        if everyone is not None:
            before = permissions
            permissions &= ~everyone.deny
            trace.append(
                self._trace(
                    TraceStep.EVERYONE_OVERWRITE_DENY,
                    "EVERYONE_OVERWRITE",
                    guild_id,
                    0,
                    everyone.deny,
                    before,
                    permissions,
                    "permissions.trace.everyoneDeny",
                )
            )
            before = permissions
            permissions |= everyone.allow
            trace.append(
                self._trace(
                    TraceStep.EVERYONE_OVERWRITE_ALLOW,
                    "EVERYONE_OVERWRITE",
                    guild_id,
                    everyone.allow,
                    0,
                    before,
                    permissions,
                    "permissions.trace.everyoneAllow",
                )
            )

        member_roles = set(member.role_ids)
        role_overwrites = sorted(
            (
                overwrite
                for overwrite in channel.overwrites
                if overwrite.target_type == 0
                and overwrite.target_id != guild_id
                and overwrite.target_id in member_roles
            ),
            key=lambda overwrite: overwrite.target_id,
        )
        role_denies = 0
        role_allows = 0
        for overwrite in role_overwrites:
            role_denies |= overwrite.deny
            role_allows |= overwrite.allow
        before = permissions
        permissions &= ~role_denies
        trace.append(
            self._trace(
                TraceStep.ROLE_OVERWRITES_DENY_AGGREGATE,
                "ROLE_OVERWRITE_SET",
                None,
                0,
                role_denies,
                before,
                permissions,
                "permissions.trace.roleDeniesAggregate",
            )
        )
        before = permissions
        permissions |= role_allows
        trace.append(
            self._trace(
                TraceStep.ROLE_OVERWRITES_ALLOW_AGGREGATE,
                "ROLE_OVERWRITE_SET",
                None,
                role_allows,
                0,
                before,
                permissions,
                "permissions.trace.roleAllowsAggregate",
            )
        )

        member_overwrite = next(
            (
                overwrite
                for overwrite in channel.overwrites
                if overwrite.target_type == 1 and overwrite.target_id == member.user_id
            ),
            None,
        )
        if member_overwrite is not None:
            before = permissions
            permissions &= ~member_overwrite.deny
            trace.append(
                self._trace(
                    TraceStep.MEMBER_OVERWRITE_DENY,
                    "MEMBER_OVERWRITE",
                    member.user_id,
                    0,
                    member_overwrite.deny,
                    before,
                    permissions,
                    "permissions.trace.memberDeny",
                )
            )
            before = permissions
            permissions |= member_overwrite.allow
            trace.append(
                self._trace(
                    TraceStep.MEMBER_OVERWRITE_ALLOW,
                    "MEMBER_OVERWRITE",
                    member.user_id,
                    member_overwrite.allow,
                    0,
                    before,
                    permissions,
                    "permissions.trace.memberAllow",
                )
            )
        return permissions

    def _apply_implicit_permissions(
        self,
        calculated: int,
        *,
        resource: ChannelSnapshot | None,
        member: MemberSnapshot,
        incomplete: list[str],
        warnings: list[str],
        trace: list[PermissionTraceEntry],
    ) -> tuple[int, list[ImplicitDenial]]:
        if resource is None:
            return calculated, []
        effective = calculated
        denials: list[ImplicitDenial] = []
        view = self.registry.value("VIEW_CHANNEL")
        if not effective & view:
            denied = self._channel_known_mask(resource.channel_type) & effective
            effective &= ~denied
            denials.append(
                ImplicitDenial(denied, "VIEW_CHANNEL", "permissions.implicit.viewChannel")
            )
            trace.append(self._implicit_trace(resource.channel_id, calculated, effective, denied))
            return effective, denials

        if resource.is_thread:
            send = self.registry.value("SEND_MESSAGES")
            if effective & send:
                before = effective
                effective &= ~send
                denied = before ^ effective
                denials.append(
                    ImplicitDenial(
                        denied,
                        "SEND_MESSAGES_IN_THREADS",
                        "permissions.implicit.sendMessagesIgnoredInThread",
                    )
                )
                trace.append(self._implicit_trace(resource.channel_id, before, effective, denied))
            manage_threads = self.registry.value("MANAGE_THREADS")
            if resource.channel_type is ChannelType.PRIVATE_THREAD and not (
                effective & manage_threads
            ):
                if not member.private_thread_memberships_complete:
                    incomplete.append("permissions.private_thread_membership_unknown")
                elif resource.channel_id not in member.private_thread_memberships:
                    before = effective
                    denied = self._channel_known_mask(resource.channel_type) & effective
                    effective &= ~denied
                    denials.append(
                        ImplicitDenial(
                            denied,
                            "PRIVATE_THREAD_MEMBERSHIP",
                            "permissions.implicit.privateThreadMembership",
                        )
                    )
                    trace.append(
                        self._implicit_trace(resource.channel_id, before, effective, denied)
                    )
                    return effective, denials
            send_in_threads = self.registry.value("SEND_MESSAGES_IN_THREADS")
            if not effective & send_in_threads:
                effective, denial = self._remove_send_dependents(
                    effective,
                    missing="SEND_MESSAGES_IN_THREADS",
                    reason="permissions.implicit.sendMessagesInThreads",
                )
                if denial.denied_bits:
                    denials.append(denial)
                    trace.append(
                        self._implicit_trace(
                            resource.channel_id,
                            effective | denial.denied_bits,
                            effective,
                            denial.denied_bits,
                        )
                    )
            if resource.archived:
                warnings.append("permissions.thread.archived")
            if resource.locked and not effective & manage_threads:
                before = effective
                denied = effective & send_in_threads
                effective &= ~send_in_threads
                warnings.append("permissions.thread.locked_without_manage_threads")
                if denied:
                    denials.append(
                        ImplicitDenial(
                            denied,
                            "MANAGE_THREADS",
                            "permissions.implicit.lockedThread",
                        )
                    )
                    trace.append(
                        self._implicit_trace(resource.channel_id, before, effective, denied)
                    )
            return effective, denials

        send = self.registry.value("SEND_MESSAGES")
        if not effective & send and resource.channel_type in {
            ChannelType.GUILD_TEXT,
            ChannelType.GUILD_ANNOUNCEMENT,
            ChannelType.GUILD_FORUM,
            ChannelType.GUILD_MEDIA,
        }:
            before = effective
            effective, denial = self._remove_send_dependents(
                effective,
                missing="SEND_MESSAGES",
                reason="permissions.implicit.sendMessages",
            )
            if denial.denied_bits:
                denials.append(denial)
                trace.append(
                    self._implicit_trace(resource.channel_id, before, effective, denial.denied_bits)
                )

        connect = self.registry.value("CONNECT")
        if not effective & connect and resource.channel_type in {
            ChannelType.GUILD_VOICE,
            ChannelType.GUILD_STAGE_VOICE,
        }:
            before = effective
            voice_mask = 0
            applicability = (
                ChannelApplicability.VOICE
                if resource.channel_type is ChannelType.GUILD_VOICE
                else ChannelApplicability.STAGE
            )
            for flag in self.registry.flags:
                if applicability in flag.applies_to and flag.name != "VIEW_CHANNEL":
                    voice_mask |= flag.value
            denied = voice_mask & effective
            effective &= ~voice_mask
            denials.append(ImplicitDenial(denied, "CONNECT", "permissions.implicit.connect"))
            trace.append(self._implicit_trace(resource.channel_id, before, effective, denied))
        return effective, denials

    def _remove_send_dependents(
        self,
        value: int,
        *,
        missing: str,
        reason: str,
    ) -> tuple[int, ImplicitDenial]:
        names = [
            "MENTION_EVERYONE",
            "SEND_TTS_MESSAGES",
            "ATTACH_FILES",
            "EMBED_LINKS",
        ]
        mask = 0
        for name in names:
            mask |= self.registry.value(name)
        denied = value & mask
        return value & ~mask, ImplicitDenial(denied, missing, reason)

    def _channel_known_mask(self, channel_type: ChannelType | int) -> int:
        applicability = self._channel_applicability(channel_type)
        if applicability is None:
            return 0
        return sum(flag.value for flag in self.registry.flags if applicability in flag.applies_to)

    @staticmethod
    def _channel_applicability(
        channel_type: ChannelType | int,
    ) -> ChannelApplicability | None:
        if channel_type in {
            ChannelType.GUILD_TEXT,
            ChannelType.GUILD_ANNOUNCEMENT,
            ChannelType.GUILD_FORUM,
            ChannelType.GUILD_MEDIA,
            ChannelType.ANNOUNCEMENT_THREAD,
            ChannelType.PUBLIC_THREAD,
            ChannelType.PRIVATE_THREAD,
        }:
            return ChannelApplicability.TEXT
        elif channel_type is ChannelType.GUILD_STAGE_VOICE:
            return ChannelApplicability.STAGE
        elif channel_type is ChannelType.GUILD_VOICE:
            return ChannelApplicability.VOICE
        else:
            return None

    @staticmethod
    def _validate_tenant(
        guild: GuildSnapshot,
        member: MemberSnapshot,
        resource: ChannelSnapshot | None,
        parent: ChannelSnapshot | None,
    ) -> None:
        values = [member.guild_id]
        if resource is not None:
            values.append(resource.guild_id)
        if parent is not None:
            values.append(parent.guild_id)
        if any(guild_id != guild.guild_id for guild_id in values):
            raise ValueError("permission inputs cross a tenant boundary")

    @staticmethod
    def _trace(
        step: TraceStep,
        source_type: str,
        source_id: int | None,
        allow_bits: int,
        deny_bits: int,
        before: int,
        after: int,
        reason_key: str,
    ) -> PermissionTraceEntry:
        return PermissionTraceEntry(
            step, source_type, source_id, allow_bits, deny_bits, before, after, reason_key
        )

    def _implicit_trace(
        self, resource_id: int, before: int, after: int, denied: int
    ) -> PermissionTraceEntry:
        return self._trace(
            TraceStep.IMPLICIT_DENIAL,
            "CHANNEL",
            resource_id,
            0,
            denied,
            before,
            after,
            "permissions.trace.implicitDenial",
        )
