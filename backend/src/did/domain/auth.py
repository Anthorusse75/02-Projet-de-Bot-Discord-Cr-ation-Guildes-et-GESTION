from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

DISCORD_ADMINISTRATOR = 1 << 3


class InstallationStatus(StrEnum):
    DISCOVERED = "DISCOVERED"
    INSTALLED = "INSTALLED"
    PENDING_SETUP = "PENDING_SETUP"
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    REVOKED = "REVOKED"
    UNINSTALLED = "UNINSTALLED"


class PlatformRole(StrEnum):
    OWNER = "OWNER"
    TENANT_ADMIN = "TENANT_ADMIN"
    READ_ONLY = "READ_ONLY"


class AccessStatus(StrEnum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class ScopeKind(StrEnum):
    GUILD = "GUILD"
    LOGICAL_GROUP = "LOGICAL_GROUP"
    VISIBILITY_SCOPE = "VISIBILITY_SCOPE"


@dataclass(frozen=True, slots=True)
class AuthorizationScope:
    kind: ScopeKind
    scope_id: str

    def __post_init__(self) -> None:
        if self.kind is ScopeKind.GUILD:
            if self.scope_id != "*":
                raise ValueError("GUILD scope_id must be the canonical wildcard")
            return
        if not self.scope_id or not self.scope_id.strip() or self.scope_id == "*":
            raise ValueError("limited scope_id must be explicit and non-empty")
        if self.scope_id != self.scope_id.strip():
            raise ValueError("scope_id cannot contain surrounding whitespace")

    @classmethod
    def guild(cls) -> "AuthorizationScope":
        return cls(ScopeKind.GUILD, "*")

    def covers(self, target: "AuthorizationScope") -> bool:
        return self.kind is ScopeKind.GUILD or self == target


class Capability(StrEnum):
    TENANT_READ = "tenant.read"
    TENANT_BOOTSTRAP = "tenant.bootstrap"
    RBAC_READ = "rbac.read"
    RBAC_WRITE = "rbac.write"
    STRUCTURE_READ = "structure.read"
    STRUCTURE_WRITE = "structure.write"
    STRUCTURE_DELETE = "structure.delete"
    ROLES_READ = "roles.read"
    ROLES_WRITE = "roles.write"
    MEMBERS_READ = "members.read"
    MEMBERS_WRITE = "members.write"
    BOTS_READ = "bots.read"
    BOTS_AUDIT = "bots.audit"
    PERMISSIONS_READ = "permissions.read"
    PERMISSIONS_WRITE = "permissions.write"
    PLANS_CREATE = "plans.create"
    PLANS_APPLY = "plans.apply"
    AUDIT_READ = "audit.read"
    TEMPLATES_READ = "templates.read"
    TEMPLATES_WRITE = "templates.write"
    MESSAGES_PUBLISH = "messages.publish"


READ_ONLY_CAPABILITIES = frozenset(
    {
        Capability.TENANT_READ,
        Capability.RBAC_READ,
        Capability.STRUCTURE_READ,
        Capability.ROLES_READ,
        Capability.MEMBERS_READ,
        Capability.BOTS_READ,
        Capability.PERMISSIONS_READ,
        Capability.AUDIT_READ,
        Capability.TEMPLATES_READ,
    }
)
TENANT_ADMIN_CAPABILITIES = frozenset(Capability)
ROLE_CAPABILITIES: dict[PlatformRole, frozenset[Capability]] = {
    PlatformRole.OWNER: frozenset(Capability),
    PlatformRole.TENANT_ADMIN: TENANT_ADMIN_CAPABILITIES,
    PlatformRole.READ_ONLY: READ_ONLY_CAPABILITIES,
}


@dataclass(frozen=True, slots=True)
class GuildDiscovery:
    guild_id: int
    name: str
    icon_hash: str | None
    owner: bool
    permissions: int

    def __post_init__(self) -> None:
        if self.guild_id <= 0:
            raise ValueError("guild_id must be positive")
        if self.permissions < 0:
            raise ValueError("permissions cannot be negative")

    @property
    def can_bootstrap(self) -> bool:
        return self.owner or bool(self.permissions & DISCORD_ADMINISTRATOR)


@dataclass(frozen=True, slots=True)
class ActorMembership:
    guild_id: int
    discord_user_id: int
    role_ids: tuple[int, ...]
    observed_at: datetime
    source: str

    def is_fresh(self, *, max_age_seconds: int, now: datetime | None = None) -> bool:
        reference = now or datetime.now(UTC)
        observed = self.observed_at
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=UTC)
        return reference - observed <= timedelta(seconds=max_age_seconds)


def capabilities_for_role(role: PlatformRole) -> frozenset[Capability]:
    return ROLE_CAPABILITIES[role]


def bootstrap_allowed(*, owner: bool, permissions: int) -> bool:
    return owner or bool(permissions & DISCORD_ADMINISTRATOR)
