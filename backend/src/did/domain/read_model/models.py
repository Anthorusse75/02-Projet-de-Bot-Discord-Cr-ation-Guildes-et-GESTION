from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum, StrEnum

from did.domain.discord_runtime import CoverageMode, FreshnessState, ObservabilityState


class ResourceKind(StrEnum):
    DISCORD_RESOURCE = "DISCORD_RESOURCE"
    DID_LOGICAL_RESOURCE = "DID_LOGICAL_RESOURCE"


class ActiveThreadCoverageState(StrEnum):
    ACTIVE_VISIBLE_THREADS_FULL = "ACTIVE_VISIBLE_THREADS_FULL"
    PARTIAL = "PARTIAL"
    DEGRADED = "DEGRADED"
    UNKNOWN = "UNKNOWN"


class ThreadActiveState(StrEnum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    NOT_IN_ACTIVE_SYNC = "NOT_IN_ACTIVE_SYNC"
    UNKNOWN = "UNKNOWN"


class ChannelType(IntEnum):
    GUILD_TEXT = 0
    GUILD_VOICE = 2
    GUILD_CATEGORY = 4
    GUILD_ANNOUNCEMENT = 5
    ANNOUNCEMENT_THREAD = 10
    PUBLIC_THREAD = 11
    PRIVATE_THREAD = 12
    GUILD_STAGE_VOICE = 13
    GUILD_DIRECTORY = 14
    GUILD_FORUM = 15
    GUILD_MEDIA = 16

    @property
    def is_thread(self) -> bool:
        return self in {
            ChannelType.ANNOUNCEMENT_THREAD,
            ChannelType.PUBLIC_THREAD,
            ChannelType.PRIVATE_THREAD,
        }


@dataclass(frozen=True, slots=True)
class FreshnessSnapshot:
    state: FreshnessState
    source: str
    state_version: int
    cache_updated_at: datetime | None
    last_full_observed_at: datetime | None = None
    last_gateway_seen_at: datetime | None = None
    last_rest_seen_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.state_version <= 0:
            raise ValueError("state_version must be positive")
        for value in (
            self.cache_updated_at,
            self.last_full_observed_at,
            self.last_gateway_seen_at,
            self.last_rest_seen_at,
        ):
            if value is not None and value.tzinfo is None:
                raise ValueError("snapshot timestamps must be timezone-aware")


@dataclass(frozen=True, slots=True)
class CoverageSnapshot:
    guild_id: int
    mode: CoverageMode
    freshness: FreshnessState
    source: str
    state_version: int
    known_channels: int = 0
    visible_channels: int = 0
    obfuscated_channels: int = 0
    known_roles: int = 0
    members_complete: bool = False
    overwrites_complete: bool = False
    threads_complete: bool = False
    gateway_continuity: str = "UNKNOWN"
    active_threads_coverage: ActiveThreadCoverageState = ActiveThreadCoverageState.UNKNOWN

    def __post_init__(self) -> None:
        if self.guild_id <= 0 or self.state_version <= 0:
            raise ValueError("coverage identifiers and version must be positive")
        if (
            min(
                self.known_channels,
                self.visible_channels,
                self.obfuscated_channels,
                self.known_roles,
            )
            < 0
        ):
            raise ValueError("coverage counts cannot be negative")


@dataclass(frozen=True, slots=True)
class OverwriteSnapshot:
    guild_id: int
    channel_id: int
    target_id: int
    target_type: int
    allow: int
    deny: int
    observed_at: datetime | None = None

    def __post_init__(self) -> None:
        if min(self.guild_id, self.channel_id, self.target_id) <= 0:
            raise ValueError("Discord identifiers must be positive")
        if self.target_type not in (0, 1):
            raise ValueError("overwrite target_type must be role (0) or member (1)")
        if self.allow < 0 or self.deny < 0:
            raise ValueError("permission bitfields cannot be negative")
        if self.observed_at is not None and self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class RoleSnapshot:
    guild_id: int
    role_id: int
    name: str
    position: int
    permissions: int
    managed: bool
    freshness: FreshnessSnapshot

    def __post_init__(self) -> None:
        if min(self.guild_id, self.role_id) <= 0:
            raise ValueError("Discord identifiers must be positive")
        if self.position < 0 or self.permissions < 0:
            raise ValueError("role position and permissions cannot be negative")


@dataclass(frozen=True, slots=True)
class MemberSnapshot:
    guild_id: int
    user_id: int
    role_ids: tuple[int, ...]
    roles_complete: bool
    freshness: FreshnessSnapshot
    is_bot: bool = False
    private_thread_memberships: frozenset[int] = frozenset()
    private_thread_memberships_complete: bool = False
    private_thread_membership_known: frozenset[int] = frozenset()

    def __post_init__(self) -> None:
        if min(self.guild_id, self.user_id) <= 0:
            raise ValueError("Discord identifiers must be positive")
        if len(set(self.role_ids)) != len(self.role_ids) or any(
            role <= 0 for role in self.role_ids
        ):
            raise ValueError("member role_ids must be unique positive Snowflakes")
        if any(value <= 0 for value in self.private_thread_membership_known):
            raise ValueError("known private thread memberships must be positive Snowflakes")


@dataclass(frozen=True, slots=True)
class ChannelSnapshot:
    guild_id: int
    channel_id: int
    channel_type: ChannelType | int
    position: int
    parent_id: int | None
    name: str | None
    overwrites: tuple[OverwriteSnapshot, ...]
    overwrites_complete: bool
    observability: ObservabilityState
    freshness: FreshnessSnapshot
    resource_kind: ResourceKind = ResourceKind.DISCORD_RESOURCE
    archived: bool | None = None
    locked: bool | None = None
    thread_active_state: ThreadActiveState | None = None

    def __post_init__(self) -> None:
        if min(self.guild_id, self.channel_id) <= 0:
            raise ValueError("Discord identifiers must be positive")
        if self.parent_id is not None and self.parent_id <= 0:
            raise ValueError("parent_id must be a positive Snowflake")
        if self.position < 0:
            raise ValueError("channel position cannot be negative")
        if self.channel_type == ChannelType.GUILD_CATEGORY and self.parent_id is not None:
            raise ValueError("Discord categories cannot have a parent category")
        if any(
            overwrite.guild_id != self.guild_id or overwrite.channel_id != self.channel_id
            for overwrite in self.overwrites
        ):
            raise ValueError("overwrite must belong to the channel tenant")
        targets = [(overwrite.target_type, overwrite.target_id) for overwrite in self.overwrites]
        if len(targets) != len(set(targets)):
            raise ValueError("channel overwrites must have unique role/member targets")

    @property
    def is_thread(self) -> bool:
        return self.channel_type in {
            ChannelType.ANNOUNCEMENT_THREAD,
            ChannelType.PUBLIC_THREAD,
            ChannelType.PRIVATE_THREAD,
        }


@dataclass(frozen=True, slots=True)
class GuildSnapshot:
    guild_id: int
    owner_id: int
    roles: tuple[RoleSnapshot, ...]
    channels: tuple[ChannelSnapshot, ...]
    coverage: CoverageSnapshot
    freshness: FreshnessSnapshot
    roles_complete: bool = True
    channels_complete: bool = True
    source_versions: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if min(self.guild_id, self.owner_id) <= 0:
            raise ValueError("Discord identifiers must be positive")
        if self.coverage.guild_id != self.guild_id:
            raise ValueError("coverage must belong to the guild")
        if any(role.guild_id != self.guild_id for role in self.roles):
            raise ValueError("role belongs to another guild")
        if any(channel.guild_id != self.guild_id for channel in self.channels):
            raise ValueError("channel belongs to another guild")

    def role(self, role_id: int) -> RoleSnapshot | None:
        return next((role for role in self.roles if role.role_id == role_id), None)

    def channel(self, channel_id: int) -> ChannelSnapshot | None:
        return next(
            (channel for channel in self.channels if channel.channel_id == channel_id), None
        )
