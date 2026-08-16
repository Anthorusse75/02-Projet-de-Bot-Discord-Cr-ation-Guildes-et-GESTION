import re
from dataclasses import dataclass

from redis.asyncio import Redis

_SEGMENT = re.compile(r"^[a-z0-9][a-z0-9:_-]*$")


@dataclass(frozen=True, slots=True)
class GuildRedisNamespace:
    guild_id: int

    def __post_init__(self) -> None:
        if self.guild_id <= 0:
            raise ValueError("guild_id must be positive")

    def key(self, *segments: str) -> str:
        if not segments or any(not _SEGMENT.fullmatch(segment) for segment in segments):
            raise ValueError("Redis key segments must be explicit lowercase safe segments")
        return f"did:guild:{self.guild_id}:{':'.join(segments)}"


def guild_namespace(guild_id: int) -> GuildRedisNamespace:
    return GuildRedisNamespace(guild_id)


def user_control_key(*segments: str) -> str:
    if not segments or any(not _SEGMENT.fullmatch(segment) for segment in segments):
        raise ValueError("Redis key segments must be explicit lowercase safe segments")
    return f"did:user-control:{':'.join(segments)}"


def create_redis_client(redis_url: str) -> Redis:
    return Redis.from_url(redis_url, decode_responses=True)


async def redis_is_ready(client: Redis) -> bool:
    try:
        return bool(await client.ping())
    except Exception:  # readiness translates backend failures to a boolean
        return False
