import hashlib
import hmac
import json
import math
import secrets
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis

from did.domain.auth import ActorMembership
from did.infrastructure.redis import user_control_key
from did.oauth.models import DiscordGuild


class OAuthStateError(ValueError):
    pass


class SessionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class OAuthState:
    state: str
    return_to: str


@dataclass(frozen=True, slots=True)
class SessionData:
    session_id: str
    discord_user_id: int
    csrf_token: str
    active_guild_id: int | None
    created_at: datetime
    last_seen_at: datetime
    absolute_expires_at: datetime
    policy_version: int


class RedisOAuthStateStore:
    def __init__(self, redis: Redis, *, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl_seconds = ttl_seconds

    async def create(self, *, return_to: str) -> OAuthState:
        if not _is_local_path(return_to):
            raise OAuthStateError("OAuth return path is not allowlisted")
        state = secrets.token_urlsafe(32)
        key = user_control_key("oauth-state", hashlib.sha256(state.encode()).hexdigest())
        payload = json.dumps({"return_to": return_to}, separators=(",", ":"))
        created = await self._redis.set(key, payload, ex=self._ttl_seconds, nx=True)
        if not created:
            raise OAuthStateError("OAuth state collision")
        return OAuthState(state=state, return_to=return_to)

    async def consume(self, state: str) -> OAuthState:
        if not state:
            raise OAuthStateError("OAuth state is missing")
        key = user_control_key("oauth-state", hashlib.sha256(state.encode()).hexdigest())
        payload = await self._redis.getdel(key)
        if not isinstance(payload, str):
            raise OAuthStateError("OAuth state is invalid, expired, or already used")
        try:
            return_to = json.loads(payload)["return_to"]
        except (TypeError, KeyError, json.JSONDecodeError) as exc:
            raise OAuthStateError("OAuth state record is invalid") from exc
        if not isinstance(return_to, str) or not _is_local_path(return_to):
            raise OAuthStateError("OAuth return path is invalid")
        return OAuthState(state=state, return_to=return_to)


class RedisSessionStore:
    def __init__(
        self,
        redis: Redis,
        *,
        session_secret: str,
        idle_ttl_seconds: int,
        absolute_ttl_seconds: int,
    ) -> None:
        if len(session_secret) < 32:
            raise SessionError("session secret must contain at least 32 characters")
        self._redis = redis
        self._secret = session_secret.encode()
        self._idle_ttl_seconds = idle_ttl_seconds
        self._absolute_ttl_seconds = absolute_ttl_seconds

    async def create(self, *, discord_user_id: int, previous_session_id: str | None) -> SessionData:
        if previous_session_id:
            await self.revoke(previous_session_id)
        now = datetime.now(UTC)
        session = SessionData(
            session_id=secrets.token_urlsafe(32),
            discord_user_id=discord_user_id,
            csrf_token=secrets.token_urlsafe(32),
            active_guild_id=None,
            created_at=now,
            last_seen_at=now,
            absolute_expires_at=now + timedelta(seconds=self._absolute_ttl_seconds),
            policy_version=1,
        )
        await self._write(session)
        return session

    async def load(self, session_id: str | None) -> SessionData | None:
        if not session_id:
            return None
        key = self._session_key(session_id)
        payload = await self._redis.get(key)
        if not isinstance(payload, str):
            return None
        try:
            session = _decode_session(payload, session_id)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            await self._redis.delete(key)
            return None
        now = datetime.now(UTC)
        if now >= session.absolute_expires_at:
            await self.revoke(session_id)
            return None
        touched = SessionData(
            session_id=session.session_id,
            discord_user_id=session.discord_user_id,
            csrf_token=session.csrf_token,
            active_guild_id=session.active_guild_id,
            created_at=session.created_at,
            last_seen_at=now,
            absolute_expires_at=session.absolute_expires_at,
            policy_version=session.policy_version,
        )
        await self._write(touched)
        return touched

    async def select_guild(self, session: SessionData, guild_id: int) -> SessionData:
        updated = SessionData(
            session_id=session.session_id,
            discord_user_id=session.discord_user_id,
            csrf_token=secrets.token_urlsafe(32),
            active_guild_id=guild_id,
            created_at=session.created_at,
            last_seen_at=datetime.now(UTC),
            absolute_expires_at=session.absolute_expires_at,
            policy_version=session.policy_version + 1,
        )
        await self._write(updated)
        return updated

    async def revoke(self, session_id: str) -> None:
        digest = self._digest(session_id)
        key = user_control_key("session", digest)
        payload = await self._redis.get(key)
        transaction = self._redis.pipeline(transaction=True)
        transaction.delete(key)
        if isinstance(payload, str):
            try:
                user_id = int(json.loads(payload)["discord_user_id"])
                transaction.srem(user_control_key("user", str(user_id), "sessions"), digest)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                pass
        await transaction.execute()

    async def revoke_user(self, discord_user_id: int) -> None:
        index_key = user_control_key("user", str(discord_user_id), "sessions")
        digests = await self._redis.smembers(index_key)
        keys = [user_control_key("session", str(digest)) for digest in digests]
        if keys:
            await self._redis.delete(*keys)
        await self._redis.delete(index_key)

    async def _write(self, session: SessionData) -> None:
        now = datetime.now(UTC)
        absolute_remaining = math.ceil((session.absolute_expires_at - now).total_seconds())
        if absolute_remaining <= 0:
            raise SessionError("session absolute lifetime has expired")
        ttl = min(self._idle_ttl_seconds, absolute_remaining)
        digest = self._digest(session.session_id)
        payload = asdict(session)
        payload.pop("session_id")
        for key in ("created_at", "last_seen_at", "absolute_expires_at"):
            payload[key] = payload[key].isoformat()
        transaction = self._redis.pipeline(transaction=True)
        transaction.set(
            user_control_key("session", digest),
            json.dumps(payload, separators=(",", ":")),
            ex=ttl,
        )
        index_key = user_control_key("user", str(session.discord_user_id), "sessions")
        transaction.sadd(index_key, digest)
        transaction.expire(index_key, self._absolute_ttl_seconds)
        await transaction.execute()

    def _session_key(self, session_id: str) -> str:
        return user_control_key("session", self._digest(session_id))

    def _digest(self, session_id: str) -> str:
        return hmac.new(self._secret, session_id.encode(), hashlib.sha256).hexdigest()


class RedisGuildDiscoveryStore:
    def __init__(self, redis: Redis, *, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl_seconds = ttl_seconds

    async def put(self, discord_user_id: int, guilds: tuple[DiscordGuild, ...]) -> None:
        payload = [asdict(guild) for guild in guilds]
        await self._redis.set(
            user_control_key("user", str(discord_user_id), "guilds"),
            json.dumps(payload, separators=(",", ":")),
            ex=self._ttl_seconds,
        )

    async def get(self, discord_user_id: int) -> tuple[DiscordGuild, ...] | None:
        payload = await self._redis.get(user_control_key("user", str(discord_user_id), "guilds"))
        if not isinstance(payload, str):
            return None
        try:
            items = json.loads(payload)
            if not isinstance(items, list):
                return None
            return tuple(
                DiscordGuild(
                    guild_id=int(item["guild_id"]),
                    name=str(item["name"]),
                    icon_hash=item.get("icon_hash"),
                    owner=bool(item["owner"]),
                    permissions=int(item["permissions"]),
                )
                for item in items
                if isinstance(item, dict)
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None


class RedisActorMembershipStore:
    def __init__(self, redis: Redis, *, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl_seconds = ttl_seconds

    async def put(self, membership: ActorMembership) -> None:
        payload = {
            "guild_id": membership.guild_id,
            "discord_user_id": membership.discord_user_id,
            "role_ids": membership.role_ids,
            "observed_at": membership.observed_at.isoformat(),
            "source": membership.source,
        }
        await self._redis.set(
            self._key(membership.guild_id, membership.discord_user_id),
            json.dumps(payload, separators=(",", ":")),
            ex=self._ttl_seconds * 4,
        )

    async def get(self, guild_id: int, discord_user_id: int) -> ActorMembership | None:
        payload = await self._redis.get(self._key(guild_id, discord_user_id))
        if not isinstance(payload, str):
            return None
        try:
            data = json.loads(payload)
            return ActorMembership(
                guild_id=int(data["guild_id"]),
                discord_user_id=int(data["discord_user_id"]),
                role_ids=tuple(int(role_id) for role_id in data["role_ids"]),
                observed_at=datetime.fromisoformat(data["observed_at"]),
                source=str(data["source"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def _key(self, guild_id: int, discord_user_id: int) -> str:
        return user_control_key("actor", str(discord_user_id), "guild", str(guild_id))


def _decode_session(payload: str, session_id: str) -> SessionData:
    data = json.loads(payload)
    active = data.get("active_guild_id")
    return SessionData(
        session_id=session_id,
        discord_user_id=int(data["discord_user_id"]),
        csrf_token=str(data["csrf_token"]),
        active_guild_id=None if active is None else int(active),
        created_at=datetime.fromisoformat(data["created_at"]),
        last_seen_at=datetime.fromisoformat(data["last_seen_at"]),
        absolute_expires_at=datetime.fromisoformat(data["absolute_expires_at"]),
        policy_version=int(data["policy_version"]),
    )


def _is_local_path(value: str) -> bool:
    return value.startswith("/") and not value.startswith("//") and "\\" not in value
