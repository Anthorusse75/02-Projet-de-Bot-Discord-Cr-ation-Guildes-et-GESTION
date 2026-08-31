from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from did.domain.discord_runtime import CoverageMode, FreshnessState, ObservabilityState
from did.domain.read_model import (
    ActiveThreadCoverageState,
    ChannelSnapshot,
    CoverageSnapshot,
    FreshnessSnapshot,
    GuildSnapshot,
    MemberSnapshot,
    OverwriteSnapshot,
    RoleSnapshot,
    ThreadActiveState,
)
from did.domain.read_model.models import ChannelType
from did.domain.scopes import MembershipRuleType, ScopeMembershipRule, ScopeType, VisibilityScope
from did.infrastructure.database import tenant_transaction
from did.tenancy import TenantContext


class Stage04NotFound(LookupError):
    pass


class Stage04Repository:
    """Batch, tenant-scoped PostgreSQL projection and local DID configuration repository."""

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def guild_snapshot(
        self, guild_id: int, member_id: int
    ) -> tuple[GuildSnapshot, MemberSnapshot]:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            installation = (
                (
                    await session.execute(
                        text(
                            "SELECT guild_id, owner_id, version, last_gateway_seen_at "
                            "FROM guild_installations WHERE guild_id=:guild_id"
                        ),
                        {"guild_id": guild_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if installation is None or installation["owner_id"] is None:
                raise Stage04NotFound("guild snapshot is unavailable")
            coverage_row = (
                (
                    await session.execute(
                        text("SELECT * FROM discord_cache_coverage WHERE guild_id=:guild_id"),
                        {"guild_id": guild_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            role_rows = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM discord_roles_cache WHERE guild_id=:guild_id "
                            "AND deleted_confirmed_at IS NULL ORDER BY position, role_id"
                        ),
                        {"guild_id": guild_id},
                    )
                )
                .mappings()
                .all()
            )
            channel_rows = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM discord_channels_cache WHERE guild_id=:guild_id "
                            "ORDER BY position, channel_id"
                        ),
                        {"guild_id": guild_id},
                    )
                )
                .mappings()
                .all()
            )
            overwrite_rows = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM channel_overwrites_cache WHERE guild_id=:guild_id "
                            "ORDER BY channel_id, target_type, target_id"
                        ),
                        {"guild_id": guild_id},
                    )
                )
                .mappings()
                .all()
            )
            member_row = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM discord_member_authorization_cache "
                            "WHERE guild_id=:guild_id AND discord_user_id=:member_id"
                        ),
                        {"guild_id": guild_id, "member_id": member_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            membership_rows = (
                (
                    await session.execute(
                        text(
                            "SELECT thread_id, membership_state FROM "
                            "discord_current_thread_memberships WHERE guild_id=:guild_id "
                            "AND discord_user_id=:member_id"
                        ),
                        {"guild_id": guild_id, "member_id": member_id},
                    )
                )
                .mappings()
                .all()
            )
        coverage = self._coverage(guild_id, coverage_row)
        role_freshness = coverage.freshness
        roles = tuple(
            RoleSnapshot(
                guild_id,
                int(row["role_id"]),
                str(row["name"]),
                int(row["position"]),
                self._bits(row["permissions_bits"]),
                bool(row["managed"]),
                FreshnessSnapshot(
                    role_freshness,
                    "LOCAL_CACHE",
                    int(row["state_version"]),
                    row["cache_updated_at"],
                    last_gateway_seen_at=row["last_gateway_seen_at"],
                    last_rest_seen_at=row["last_rest_seen_at"],
                ),
                color=int(row["color"]),
                hoist=bool(row["hoist"]),
                mentionable=bool(row["mentionable"]),
            )
            for row in role_rows
        )
        by_channel: dict[int, list[OverwriteSnapshot]] = defaultdict(list)
        for row in overwrite_rows:
            by_channel[int(row["channel_id"])].append(
                OverwriteSnapshot(
                    guild_id,
                    int(row["channel_id"]),
                    int(row["target_id"]),
                    int(row["target_type"]),
                    self._bits(row["allow_bits"]),
                    self._bits(row["deny_bits"]),
                    row["last_full_observed_at"],
                )
            )
        channels: list[ChannelSnapshot] = []
        for row in channel_rows:
            raw_type = int(row["type"])
            try:
                channel_type: ChannelType | int = ChannelType(raw_type)
            except ValueError:
                channel_type = raw_type
            full_payload = row["last_full_payload"] or {}
            observability = ObservabilityState(str(row["observability_state"]))
            channels.append(
                ChannelSnapshot(
                    guild_id,
                    int(row["channel_id"]),
                    channel_type,
                    int(row["position"]),
                    int(row["parent_id"]) if row["parent_id"] is not None else None,
                    str(row["name"]) if row["name"] is not None else None,
                    tuple(by_channel[int(row["channel_id"])]),
                    observability is ObservabilityState.VISIBLE
                    and row["last_full_observed_at"] is not None,
                    observability,
                    FreshnessSnapshot(
                        FreshnessState(str(row["freshness_state"])),
                        "LOCAL_CACHE",
                        int(row["state_version"]),
                        row["cache_updated_at"],
                        row["last_full_observed_at"],
                        row["last_gateway_seen_at"],
                        row["last_rest_seen_at"],
                    ),
                    archived=full_payload.get("archived"),
                    locked=full_payload.get("locked"),
                    thread_active_state=(
                        ThreadActiveState(str(row["thread_active_state"]))
                        if row["thread_active_state"] is not None
                        else None
                    ),
                    topic=(
                        str(full_payload["topic"])
                        if full_payload.get("topic") is not None
                        else None
                    ),
                    nsfw=(
                        bool(full_payload["nsfw"]) if full_payload.get("nsfw") is not None else None
                    ),
                    flags=int(row["flags"]),
                    bitrate=(
                        int(full_payload["bitrate"])
                        if full_payload.get("bitrate") is not None
                        else None
                    ),
                    user_limit=(
                        int(full_payload["user_limit"])
                        if full_payload.get("user_limit") is not None
                        else None
                    ),
                    rate_limit_per_user=(
                        int(full_payload["rate_limit_per_user"])
                        if full_payload.get("rate_limit_per_user") is not None
                        else None
                    ),
                    default_auto_archive_duration=(
                        int(full_payload["default_auto_archive_duration"])
                        if full_payload.get("default_auto_archive_duration") is not None
                        else None
                    ),
                )
            )
        member = self._member(guild_id, member_id, member_row, membership_rows)
        guild_freshness = FreshnessSnapshot(
            coverage.freshness,
            "LOCAL_CACHE",
            int(installation["version"]),
            installation["last_gateway_seen_at"],
            last_gateway_seen_at=installation["last_gateway_seen_at"],
        )
        return GuildSnapshot(
            guild_id,
            int(installation["owner_id"]),
            roles,
            tuple(channels),
            coverage,
            guild_freshness,
            roles_complete=coverage.mode is CoverageMode.FULL and bool(roles),
            channels_complete=coverage.mode is CoverageMode.FULL,
            source_versions=(
                f"guild:{int(installation['version'])}",
                f"coverage:{coverage.state_version}",
            ),
        ), member

    async def member_snapshots(
        self, guild_id: int, member_ids: tuple[int, ...]
    ) -> tuple[MemberSnapshot, ...]:
        if not member_ids:
            return ()
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM discord_member_authorization_cache "
                            "WHERE guild_id=:guild_id AND discord_user_id = ANY(:member_ids)"
                        ),
                        {"guild_id": guild_id, "member_ids": list(member_ids)},
                    )
                )
                .mappings()
                .all()
            )
            membership_rows = (
                (
                    await session.execute(
                        text(
                            "SELECT thread_id, discord_user_id, membership_state FROM "
                            "discord_current_thread_memberships WHERE guild_id=:guild_id "
                            "AND discord_user_id = ANY(:member_ids)"
                        ),
                        {"guild_id": guild_id, "member_ids": list(member_ids)},
                    )
                )
                .mappings()
                .all()
            )
        by_id = {int(row["discord_user_id"]): row for row in rows}
        memberships_by_member: dict[int, list[Any]] = defaultdict(list)
        for membership in membership_rows:
            memberships_by_member[int(membership["discord_user_id"])].append(membership)
        return tuple(
            self._member(
                guild_id,
                member_id,
                by_id.get(member_id),
                memberships_by_member.get(member_id, []),
            )
            for member_id in member_ids
        )

    async def member_ids_with_role(self, guild_id: int, role_id: int) -> tuple[int, ...]:
        """Return cached assignees; callers must separately require complete member coverage."""
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT discord_user_id FROM discord_member_authorization_cache "
                        "WHERE guild_id=:guild_id AND :role_id = ANY(role_ids) "
                        "AND validity='FRESH' ORDER BY discord_user_id"
                    ),
                    {"guild_id": guild_id, "role_id": role_id},
                )
            ).scalars()
            return tuple(int(value) for value in rows)

    async def cached_member_snapshots(self, guild_id: int) -> tuple[MemberSnapshot, ...]:
        """Return only locally known subjects; this never invokes Discord member listing."""
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            member_ids = tuple(
                int(value)
                for value in (
                    await session.execute(
                        text(
                            "SELECT discord_user_id FROM discord_member_authorization_cache "
                            "WHERE guild_id=:guild_id ORDER BY discord_user_id"
                        ),
                        {"guild_id": guild_id},
                    )
                ).scalars()
            )
        return await self.member_snapshots(guild_id, member_ids)

    async def bot_identity(self, guild_id: int) -> tuple[int | None, str | None]:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT bot_user_id, installation_status FROM guild_installations "
                            "WHERE guild_id=:guild_id"
                        ),
                        {"guild_id": guild_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None, None
        return (
            int(row["bot_user_id"]) if row["bot_user_id"] is not None else None,
            str(row["installation_status"]),
        )

    async def structure(self, guild_id: int) -> dict[str, Any]:
        snapshot, _ = await self.guild_snapshot(guild_id, guild_id)
        categories = [channel for channel in snapshot.channels if channel.channel_type == 4]
        category_ids = {category.channel_id for category in categories}
        children: dict[int, list[ChannelSnapshot]] = defaultdict(list)
        roots: list[ChannelSnapshot] = []
        threads: dict[int, list[ChannelSnapshot]] = defaultdict(list)
        for channel in snapshot.channels:
            if channel.channel_type == 4:
                continue
            if channel.is_thread and channel.parent_id is not None:
                threads[channel.parent_id].append(channel)
            elif channel.parent_id in category_ids:
                assert channel.parent_id is not None
                children[channel.parent_id].append(channel)
            else:
                roots.append(channel)
        return {
            "snapshot": snapshot,
            "categories": categories,
            "children": children,
            "roots": roots,
            "threads": threads,
        }

    async def list_logical_groups(self, guild_id: int) -> list[dict[str, Any]]:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            groups = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM logical_groups WHERE guild_id=:guild_id "
                            "ORDER BY slug, id"
                        ),
                        {"guild_id": guild_id},
                    )
                )
                .mappings()
                .all()
            )
            resources = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM logical_group_resources WHERE guild_id=:guild_id "
                            "ORDER BY logical_group_id, resource_type, id"
                        ),
                        {"guild_id": guild_id},
                    )
                )
                .mappings()
                .all()
            )
        grouped: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
        for item in resources:
            grouped[item["logical_group_id"]].append(dict(item))
        return [{**dict(group), "resources": grouped[group["id"]]} for group in groups]

    async def create_logical_group(
        self,
        *,
        guild_id: int,
        actor_id: int,
        name: str,
        slug: str,
        description: str | None,
        metadata: dict[str, Any],
        resources: tuple[dict[str, Any], ...],
        group_id: UUID | None = None,
    ) -> UUID:
        group_id = group_id or uuid4()
        correlation_id = uuid4()
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            created = await session.scalar(
                text(
                    "INSERT INTO logical_groups "
                    "(id,guild_id,name,slug,description,metadata_json) VALUES "
                    "(:id,:guild_id,:name,:slug,:description,CAST(:metadata AS jsonb)) "
                    "ON CONFLICT (guild_id,id) DO NOTHING RETURNING id"
                ),
                {
                    "id": group_id,
                    "guild_id": guild_id,
                    "name": name,
                    "slug": slug,
                    "description": description,
                    "metadata": json.dumps(metadata, separators=(",", ":")),
                },
            )
            if created is not None:
                for resource in resources:
                    await self._insert_group_resource(session, guild_id, group_id, resource)
                await self._audit(
                    session,
                    guild_id,
                    actor_id,
                    "LOGICAL_GROUP_CREATED",
                    "LOGICAL_GROUP",
                    group_id,
                    correlation_id,
                )
        return group_id

    async def update_logical_group(
        self,
        *,
        guild_id: int,
        group_id: UUID,
        actor_id: int,
        name: str,
        description: str | None,
        metadata: dict[str, Any],
        resources: tuple[dict[str, Any], ...] | None = None,
    ) -> None:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            updated = await session.scalar(
                text(
                    "UPDATE logical_groups SET name=:name, description=:description, "
                    "metadata_json=CAST(:metadata AS jsonb), version=version+1, updated_at=now() "
                    "WHERE guild_id=:guild_id AND id=:id RETURNING id"
                ),
                {
                    "guild_id": guild_id,
                    "id": group_id,
                    "name": name,
                    "description": description,
                    "metadata": json.dumps(metadata, separators=(",", ":")),
                },
            )
            if updated is None:
                raise Stage04NotFound("logical group not found")
            if resources is not None:
                await session.execute(
                    text(
                        "DELETE FROM logical_group_resources "
                        "WHERE guild_id=:guild_id AND logical_group_id=:id"
                    ),
                    {"guild_id": guild_id, "id": group_id},
                )
                for resource in resources:
                    await self._insert_group_resource(session, guild_id, group_id, resource)
            await self._audit(
                session,
                guild_id,
                actor_id,
                "LOGICAL_GROUP_UPDATED",
                "LOGICAL_GROUP",
                group_id,
                uuid4(),
            )

    async def delete_logical_group(self, guild_id: int, group_id: UUID, actor_id: int) -> None:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            deleted = await session.scalar(
                text("DELETE FROM logical_groups WHERE guild_id=:guild_id AND id=:id RETURNING id"),
                {"guild_id": guild_id, "id": group_id},
            )
            if deleted is None:
                raise Stage04NotFound("logical group not found")
            await self._audit(
                session,
                guild_id,
                actor_id,
                "LOGICAL_GROUP_DELETED",
                "LOGICAL_GROUP",
                group_id,
                uuid4(),
            )

    async def list_visibility_scopes(
        self, guild_id: int
    ) -> list[tuple[VisibilityScope, tuple[ScopeMembershipRule, ...], frozenset[int]]]:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            scopes = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM visibility_scopes WHERE guild_id=:guild_id "
                            "ORDER BY scope_key, id"
                        ),
                        {"guild_id": guild_id},
                    )
                )
                .mappings()
                .all()
            )
            rules = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM scope_membership_rules WHERE guild_id=:guild_id "
                            "ORDER BY visibility_scope_id, priority, id"
                        ),
                        {"guild_id": guild_id},
                    )
                )
                .mappings()
                .all()
            )
            memberships = (
                (
                    await session.execute(
                        text(
                            "SELECT visibility_scope_id, discord_user_id "
                            "FROM scope_explicit_memberships WHERE guild_id=:guild_id"
                        ),
                        {"guild_id": guild_id},
                    )
                )
                .mappings()
                .all()
            )
        by_scope_rules: dict[UUID, list[ScopeMembershipRule]] = defaultdict(list)
        for row in rules:
            by_scope_rules[row["visibility_scope_id"]].append(self._rule(row))
        by_scope_members: dict[UUID, set[int]] = defaultdict(set)
        for row in memberships:
            by_scope_members[row["visibility_scope_id"]].add(int(row["discord_user_id"]))
        return [
            (
                self._scope(row),
                tuple(by_scope_rules[row["id"]]),
                frozenset(by_scope_members[row["id"]]),
            )
            for row in scopes
        ]

    async def create_visibility_scope(
        self,
        *,
        guild_id: int,
        actor_id: int,
        scope_type: ScopeType,
        scope_key: str,
        name: str,
        logical_group_id: UUID | None,
        config: dict[str, Any],
        rules: tuple[dict[str, Any], ...],
        explicit_member_ids: tuple[int, ...],
    ) -> UUID:
        scope_id = uuid4()
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            await session.execute(
                text(
                    "INSERT INTO visibility_scopes "
                    "(id,guild_id,scope_type,scope_key,logical_group_id,name,config_json) VALUES "
                    "(:id,:guild_id,:scope_type,:scope_key,:logical_group_id,:name,"
                    "CAST(:config AS jsonb))"
                ),
                {
                    "id": scope_id,
                    "guild_id": guild_id,
                    "scope_type": scope_type.value,
                    "scope_key": scope_key,
                    "logical_group_id": logical_group_id,
                    "name": name,
                    "config": json.dumps(config, separators=(",", ":")),
                },
            )
            await self._replace_scope_children(
                session, guild_id, scope_id, rules, explicit_member_ids
            )
            await self._audit(
                session,
                guild_id,
                actor_id,
                "VISIBILITY_SCOPE_CREATED",
                "VISIBILITY_SCOPE",
                scope_id,
                uuid4(),
            )
        return scope_id

    async def update_visibility_scope(
        self,
        *,
        guild_id: int,
        scope_id: UUID,
        actor_id: int,
        name: str,
        config: dict[str, Any],
        rules: tuple[dict[str, Any], ...],
        explicit_member_ids: tuple[int, ...],
    ) -> None:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            updated = await session.scalar(
                text(
                    "UPDATE visibility_scopes SET name=:name, config_json=CAST(:config AS jsonb), "
                    "version=version+1, updated_at=now() WHERE guild_id=:guild_id AND id=:id "
                    "RETURNING id"
                ),
                {
                    "guild_id": guild_id,
                    "id": scope_id,
                    "name": name,
                    "config": json.dumps(config, separators=(",", ":")),
                },
            )
            if updated is None:
                raise Stage04NotFound("visibility scope not found")
            await self._replace_scope_children(
                session, guild_id, scope_id, rules, explicit_member_ids
            )
            await self._audit(
                session,
                guild_id,
                actor_id,
                "VISIBILITY_SCOPE_UPDATED",
                "VISIBILITY_SCOPE",
                scope_id,
                uuid4(),
            )

    async def delete_visibility_scope(self, guild_id: int, scope_id: UUID, actor_id: int) -> None:
        async with tenant_transaction(self._factory, TenantContext(guild_id)) as session:
            deleted = await session.scalar(
                text(
                    "DELETE FROM visibility_scopes WHERE guild_id=:guild_id AND id=:id RETURNING id"
                ),
                {"guild_id": guild_id, "id": scope_id},
            )
            if deleted is None:
                raise Stage04NotFound("visibility scope not found")
            await self._audit(
                session,
                guild_id,
                actor_id,
                "VISIBILITY_SCOPE_DELETED",
                "VISIBILITY_SCOPE",
                scope_id,
                uuid4(),
            )

    async def _insert_group_resource(
        self,
        session: AsyncSession,
        guild_id: int,
        group_id: UUID,
        resource: dict[str, Any],
    ) -> None:
        resource_type = str(resource["resource_type"])
        resource_id = int(resource["discord_resource_id"])
        if resource_type in {"CATEGORY", "CHANNEL"}:
            actual_type = await session.scalar(
                text(
                    "SELECT type FROM discord_channels_cache "
                    "WHERE guild_id=:guild_id AND channel_id=:resource_id"
                ),
                {"guild_id": guild_id, "resource_id": resource_id},
            )
            if actual_type is None or (resource_type == "CATEGORY") != (int(actual_type) == 4):
                raise Stage04NotFound("logical group channel target not found or type mismatch")
            channel_id, role_id = resource_id, None
        elif resource_type == "ROLE":
            exists = await session.scalar(
                text(
                    "SELECT role_id FROM discord_roles_cache "
                    "WHERE guild_id=:guild_id AND role_id=:resource_id"
                ),
                {"guild_id": guild_id, "resource_id": resource_id},
            )
            if exists is None:
                raise Stage04NotFound("logical group role target not found")
            channel_id, role_id = None, resource_id
        else:
            raise ValueError("unsupported logical group resource type")
        await session.execute(
            text(
                "INSERT INTO logical_group_resources "
                "(id,guild_id,logical_group_id,resource_type,discord_channel_id,"
                "discord_role_id,semantic_role) VALUES "
                "(:id,:guild_id,:group_id,:resource_type,:channel_id,:role_id,"
                ":semantic_role)"
            ),
            {
                "id": uuid4(),
                "guild_id": guild_id,
                "group_id": group_id,
                "resource_type": resource_type,
                "channel_id": channel_id,
                "role_id": role_id,
                "semantic_role": resource.get("semantic_role"),
            },
        )

    async def _replace_scope_children(
        self,
        session: AsyncSession,
        guild_id: int,
        scope_id: UUID,
        rules: tuple[dict[str, Any], ...],
        explicit_member_ids: tuple[int, ...],
    ) -> None:
        referenced_roles = {
            int(role_id)
            for rule in rules
            if str(rule["rule_type"]) in {"DISCORD_ROLE", "ANY_DISCORD_ROLE", "ALL_DISCORD_ROLES"}
            for role_id in rule.get("config", {}).get("role_ids", [])
        }
        if referenced_roles:
            known_roles = set(
                (
                    await session.execute(
                        text(
                            "SELECT role_id FROM discord_roles_cache "
                            "WHERE guild_id=:guild_id AND role_id = ANY(:role_ids) "
                            "AND deleted_confirmed_at IS NULL"
                        ),
                        {"guild_id": guild_id, "role_ids": list(referenced_roles)},
                    )
                )
                .scalars()
                .all()
            )
            if known_roles != referenced_roles:
                raise Stage04NotFound("scope rule references an unknown Guild role")
        await session.execute(
            text(
                "DELETE FROM scope_membership_rules "
                "WHERE guild_id=:guild_id AND visibility_scope_id=:scope_id"
            ),
            {"guild_id": guild_id, "scope_id": scope_id},
        )
        await session.execute(
            text(
                "DELETE FROM scope_explicit_memberships "
                "WHERE guild_id=:guild_id AND visibility_scope_id=:scope_id"
            ),
            {"guild_id": guild_id, "scope_id": scope_id},
        )
        for rule in rules:
            await session.execute(
                text(
                    "INSERT INTO scope_membership_rules "
                    "(id,guild_id,visibility_scope_id,rule_type,config_json,priority,status) "
                    "VALUES "
                    "(:id,:guild_id,:scope_id,:rule_type,CAST(:config AS jsonb),:priority,:status)"
                ),
                {
                    "id": uuid4(),
                    "guild_id": guild_id,
                    "scope_id": scope_id,
                    "rule_type": str(rule["rule_type"]),
                    "config": json.dumps(rule.get("config", {}), separators=(",", ":")),
                    "priority": int(rule["priority"]),
                    "status": str(rule.get("status", "ACTIVE")),
                },
            )
        for member_id in explicit_member_ids:
            await session.execute(
                text(
                    "INSERT INTO scope_explicit_memberships "
                    "(guild_id,visibility_scope_id,discord_user_id) VALUES "
                    "(:guild_id,:scope_id,:member_id)"
                ),
                {"guild_id": guild_id, "scope_id": scope_id, "member_id": member_id},
            )

    @staticmethod
    async def _audit(
        session: AsyncSession,
        guild_id: int,
        actor_id: int,
        event_type: str,
        target_type: str,
        target_id: UUID,
        correlation_id: UUID,
    ) -> None:
        await session.execute(
            text(
                "INSERT INTO internal_audit_events "
                "(id,guild_id,actor_user_id,source,event_type,target_type,target_id,"
                "correlation_id,result_state,data_json,occurred_at) VALUES "
                "(:id,:guild_id,:actor_id,'DASHBOARD',:event_type,:target_type,:target_id,"
                ":correlation_id,'SUCCEEDED',CAST('{}' AS jsonb),:occurred_at)"
            ),
            {
                "id": uuid4(),
                "guild_id": guild_id,
                "actor_id": actor_id,
                "event_type": event_type,
                "target_type": target_type,
                "target_id": str(target_id),
                "correlation_id": correlation_id,
                "occurred_at": datetime.now(UTC),
            },
        )

    @staticmethod
    def _bits(value: Decimal | int) -> int:
        return int(value)

    @staticmethod
    def _coverage(guild_id: int, row: Any) -> CoverageSnapshot:
        if row is None:
            return CoverageSnapshot(
                guild_id, CoverageMode.DEGRADED, FreshnessState.UNKNOWN, "LOCAL_CACHE", 1
            )
        return CoverageSnapshot(
            guild_id,
            CoverageMode(str(row["coverage_mode"])),
            FreshnessState(str(row["freshness_state"])),
            "LOCAL_CACHE",
            int(row["state_version"]),
            int(row["known_channels"]),
            int(row["visible_channels"]),
            int(row["obfuscated_channels"]),
            int(row["known_roles"]),
            members_complete=bool(row.get("members_complete", False)),
            overwrites_complete=str(row["coverage_mode"]) == "FULL",
            threads_complete=False,
            gateway_continuity=str(row["gateway_continuity"]),
            active_threads_coverage=ActiveThreadCoverageState(
                str(row.get("active_threads_coverage", "UNKNOWN"))
            ),
        )

    @staticmethod
    def _member(
        guild_id: int, member_id: int, row: Any, membership_rows: Any = ()
    ) -> MemberSnapshot:
        known = frozenset(int(value["thread_id"]) for value in membership_rows)
        memberships = frozenset(
            int(value["thread_id"])
            for value in membership_rows
            if str(value["membership_state"]) == "MEMBER"
        )
        if row is None:
            return MemberSnapshot(
                guild_id,
                member_id,
                (),
                False,
                FreshnessSnapshot(FreshnessState.UNKNOWN, "LOCAL_CACHE", 1, None),
                private_thread_memberships=memberships,
                private_thread_membership_known=known,
            )
        validity = str(row["validity"])
        freshness = (
            FreshnessState.FRESH
            if validity == "FRESH"
            else FreshnessState.STALE
            if validity == "STALE"
            else FreshnessState.UNKNOWN
        )
        return MemberSnapshot(
            guild_id,
            member_id,
            tuple(int(role_id) for role_id in row["role_ids"]),
            validity in {"FRESH", "STALE"},
            FreshnessSnapshot(freshness, str(row["source"]), 1, row["cache_updated_at"]),
            is_bot=bool(row.get("is_bot", False)),
            private_thread_memberships=memberships,
            private_thread_membership_known=known,
        )

    @staticmethod
    def _scope(row: Any) -> VisibilityScope:
        return VisibilityScope(
            row["id"],
            int(row["guild_id"]),
            ScopeType(str(row["scope_type"])),
            str(row["scope_key"]),
            str(row["name"]),
            row["logical_group_id"],
            dict(row["config_json"]),
            int(row["version"]),
        )

    @staticmethod
    def _rule(row: Any) -> ScopeMembershipRule:
        return ScopeMembershipRule(
            row["id"],
            int(row["guild_id"]),
            row["visibility_scope_id"],
            MembershipRuleType(str(row["rule_type"])),
            dict(row["config_json"]),
            int(row["priority"]),
            str(row["status"]),
            int(row["version"]),
        )
