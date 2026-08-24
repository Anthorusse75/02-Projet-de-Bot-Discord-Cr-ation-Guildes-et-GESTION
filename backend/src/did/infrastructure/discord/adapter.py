from __future__ import annotations

from typing import Any, Protocol

import discord

from did.domain.discord_runtime import DiscordErrorKind, DiscordFailure


class DiscordStructurePort(Protocol):
    async def fetch_channels(self, guild_id: int) -> list[dict[str, Any]]: ...

    async def fetch_roles(self, guild_id: int) -> list[dict[str, Any]]: ...

    async def fetch_member(self, guild_id: int, user_id: int) -> dict[str, Any]: ...


class DiscordAdapterError(RuntimeError):
    def __init__(self, failure: DiscordFailure) -> None:
        self.failure = failure
        super().__init__(failure.kind.value)


class DiscordPyStructureAdapter:
    """discord.py owns route buckets and 429 protocol handling below the DID governor."""

    def __init__(self, client: discord.Client) -> None:
        self._client = client

    async def _guild(self, guild_id: int) -> discord.Guild:
        cached = self._client.get_guild(guild_id)
        if cached is not None:
            return cached
        try:
            return await self._client.fetch_guild(guild_id)
        except Exception as exc:
            raise self._translate(exc) from exc

    async def fetch_channels(self, guild_id: int) -> list[dict[str, Any]]:
        guild = await self._guild(guild_id)
        try:
            channels = await guild.fetch_channels()
        except Exception as exc:
            raise self._translate(exc) from exc
        result: list[dict[str, Any]] = []
        for channel in channels:
            channel_flags = getattr(channel, "flags", None)
            flags_value = int(getattr(channel_flags, "value", channel_flags or 0))
            overwrites: list[dict[str, int]] = []
            for target, overwrite in channel.overwrites.items():
                allow, deny = overwrite.pair()
                overwrites.append(
                    {
                        "id": int(target.id),
                        "type": 0 if isinstance(target, discord.Role) else 1,
                        "allow": allow.value,
                        "deny": deny.value,
                    }
                )
            result.append(
                {
                    "channel_id": int(channel.id),
                    "type": int(channel.type.value),
                    "name": channel.name,
                    "topic": getattr(channel, "topic", None),
                    "parent_id": channel.category_id,
                    "position": channel.position,
                    "nsfw": getattr(channel, "nsfw", None),
                    "flags": flags_value,
                    "permission_overwrites": overwrites,
                }
            )
        return result

    async def fetch_roles(self, guild_id: int) -> list[dict[str, Any]]:
        guild = await self._guild(guild_id)
        try:
            roles = await guild.fetch_roles()
        except Exception as exc:
            raise self._translate(exc) from exc
        return [
            {
                "role_id": int(role.id),
                "name": role.name,
                "position": role.position,
                "permissions": role.permissions.value,
                "managed": role.managed,
                "color": role.color.value,
                "hoist": role.hoist,
                "mentionable": role.mentionable,
            }
            for role in roles
        ]

    async def fetch_member(self, guild_id: int, user_id: int) -> dict[str, Any]:
        guild = await self._guild(guild_id)
        try:
            member = await guild.fetch_member(user_id)
        except Exception as exc:
            raise self._translate(exc) from exc
        return {
            "guild_id": guild_id,
            "discord_user_id": int(member.id),
            "role_ids": [int(role.id) for role in member.roles],
        }

    @staticmethod
    def _translate(exc: Exception) -> DiscordAdapterError:
        if isinstance(exc, discord.LoginFailure):
            return DiscordAdapterError(DiscordFailure(DiscordErrorKind.UNAUTHORIZED, 401))
        if isinstance(exc, discord.Forbidden):
            return DiscordAdapterError(
                DiscordFailure(
                    DiscordErrorKind.FORBIDDEN,
                    403,
                    error_code=getattr(exc, "code", None),
                )
            )
        if isinstance(exc, discord.NotFound):
            return DiscordAdapterError(
                DiscordFailure(
                    DiscordErrorKind.NOT_FOUND,
                    404,
                    error_code=getattr(exc, "code", None),
                )
            )
        if isinstance(exc, discord.HTTPException):
            status = getattr(exc, "status", None)
            if status == 401:
                kind = DiscordErrorKind.UNAUTHORIZED
            elif status == 429:
                kind = DiscordErrorKind.RATE_LIMITED
            elif status is not None and status >= 500:
                kind = DiscordErrorKind.TRANSIENT
            else:
                kind = DiscordErrorKind.INVALID_REQUEST
            response = getattr(exc, "response", None)
            headers = getattr(response, "headers", {})
            retry_after = headers.get("Retry-After") if headers else None
            return DiscordAdapterError(
                DiscordFailure(
                    kind,
                    status,
                    retry_after_seconds=float(retry_after) if retry_after else None,
                    global_rate_limit=(headers.get("X-RateLimit-Global") == "true")
                    if headers
                    else False,
                    error_code=getattr(exc, "code", None),
                    rate_limit_scope=headers.get("X-RateLimit-Scope") if headers else None,
                )
            )
        return DiscordAdapterError(DiscordFailure(DiscordErrorKind.TRANSIENT, None))
