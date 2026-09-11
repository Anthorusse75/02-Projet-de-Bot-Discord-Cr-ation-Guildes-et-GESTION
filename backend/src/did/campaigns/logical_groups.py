"""REQ-MSG-002: expand a Stage04 dashboard logical group into the real
Discord channels it currently names -- reuses the existing Stage04 logical-
group abstraction rather than inventing a parallel Discord hierarchy.

Every channel this module names is still subject to the SAME execution-time
authorization/bot-capability re-check as any other destination (
``did.campaigns.target_resolution.resolve_target`` never trusts a cached
snapshot); this module's only job is answering "which channels does this
logical group currently mean", nothing about whether the campaign may
actually send there.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from did.infrastructure.stage04_repository import Stage04Repository

#: Discord channel types that are real message destinations. Voice/stage/
#: forum channels and categories themselves are excluded -- a CATEGORY
#: logical-group resource expands to its ordinary text-capable member
#: channels only, never the category channel itself (which cannot receive
#: a message) and never a voice-only channel a bot cannot post text into.
_MESSAGEABLE_CHANNEL_TYPES = frozenset({0, 5})  # GUILD_TEXT, GUILD_ANNOUNCEMENT
_CATEGORY_CHANNEL_TYPE = 4


@dataclass(frozen=True, slots=True)
class LogicalGroupExpansion:
    #: Real, currently-existing Discord channel ids this logical group
    #: names right now -- a CHANNEL resource contributes itself, a CATEGORY
    #: resource expands to its current messageable member channels, a ROLE
    #: resource contributes none (a role is not a message destination).
    discord_channel_ids: tuple[int, ...]


async def expand_logical_group(
    stage04_repository: Stage04Repository, *, guild_id: int, logical_group_id: UUID
) -> LogicalGroupExpansion | None:
    """Returns ``None`` when the logical group does not exist (deleted, or
    never belonged to this Guild) -- the caller (target_resolution) treats
    this the same as any other unresolvable target, never a crash."""
    groups = await stage04_repository.list_logical_groups(guild_id)
    group = next((row for row in groups if UUID(str(row["id"])) == logical_group_id), None)
    if group is None:
        return None

    channel_ids: list[int] = []
    category_ids: list[int] = []
    for resource in group["resources"]:
        resource_type = str(resource["resource_type"])
        if resource_type == "CHANNEL":
            channel_ids.append(int(resource["discord_channel_id"]))
        elif resource_type == "CATEGORY":
            category_ids.append(int(resource["discord_channel_id"]))
        # ROLE: never a message destination -- contributes nothing here.

    if category_ids:
        structure = await stage04_repository.structure(guild_id)
        children = structure["children"]
        for category_id in category_ids:
            for channel in children.get(category_id, ()):
                if channel.channel_type in _MESSAGEABLE_CHANNEL_TYPES:
                    channel_ids.append(channel.channel_id)

    # De-duplicate while preserving first-seen order (a channel could in
    # principle be named both directly and via its parent category).
    deduped = tuple(dict.fromkeys(channel_ids))
    return LogicalGroupExpansion(discord_channel_ids=deduped)
