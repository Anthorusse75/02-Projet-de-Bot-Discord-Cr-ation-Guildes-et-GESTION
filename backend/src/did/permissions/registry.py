from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ChannelApplicability(StrEnum):
    TEXT = "TEXT"
    VOICE = "VOICE"
    STAGE = "STAGE"
    GUILD = "GUILD"


@dataclass(frozen=True, slots=True)
class PermissionFlag:
    name: str
    bit: int
    applies_to: frozenset[ChannelApplicability]
    description_key: str

    @property
    def value(self) -> int:
        return 1 << self.bit


class PermissionRegistry:
    def __init__(self, *, version: str, flags: tuple[PermissionFlag, ...]) -> None:
        if len({flag.name for flag in flags}) != len(flags):
            raise ValueError("permission names must be unique")
        if len({flag.bit for flag in flags}) != len(flags):
            raise ValueError("permission bits must be unique")
        self.version = version
        self.flags = flags
        self._by_name = {flag.name: flag for flag in flags}
        self._by_bit = {flag.bit: flag for flag in flags}

    @property
    def known_mask(self) -> int:
        result = 0
        for flag in self.flags:
            result |= flag.value
        return result

    def value(self, name: str) -> int:
        try:
            return self._by_name[name].value
        except KeyError as exc:
            raise ValueError(f"unknown Discord permission: {name}") from exc

    def known_bits(self, value: int) -> int:
        return value & self.known_mask

    def unknown_bits(self, value: int) -> int:
        return value & ~self.known_mask

    def names(self, value: int) -> tuple[str, ...]:
        return tuple(flag.name for flag in self.flags if value & flag.value)

    def parse_api_bits(self, value: str) -> int:
        if not value.isascii() or not value.isdecimal():
            raise ValueError("permission bitfield must be an unsigned decimal string")
        parsed = int(value)
        if parsed < 0:
            raise ValueError("permission bitfield cannot be negative")
        return parsed

    @staticmethod
    def api_bits(value: int) -> str:
        if value < 0:
            raise ValueError("permission bitfield cannot be negative")
        return str(value)


GUILD = frozenset({ChannelApplicability.GUILD})
TEXT = frozenset({ChannelApplicability.TEXT})
VOICE = frozenset({ChannelApplicability.VOICE})
STAGE = frozenset({ChannelApplicability.STAGE})
ALL_CHANNELS = frozenset(
    {ChannelApplicability.TEXT, ChannelApplicability.VOICE, ChannelApplicability.STAGE}
)
VOICE_STAGE = frozenset({ChannelApplicability.VOICE, ChannelApplicability.STAGE})
TEXT_VOICE = frozenset({ChannelApplicability.TEXT, ChannelApplicability.VOICE})


def _flag(
    name: str, bit: int, applies_to: frozenset[ChannelApplicability] = GUILD
) -> PermissionFlag:
    return PermissionFlag(name, bit, applies_to, f"permissions.flags.{name.lower()}")


# Discord official Permissions table, consulted 2026-08-17. Bit 47 is currently unassigned.
DEFAULT_PERMISSION_REGISTRY = PermissionRegistry(
    version="discord-permissions-2026-08-17",
    flags=(
        _flag("CREATE_INSTANT_INVITE", 0, ALL_CHANNELS),
        _flag("KICK_MEMBERS", 1),
        _flag("BAN_MEMBERS", 2),
        _flag("ADMINISTRATOR", 3),
        _flag("MANAGE_CHANNELS", 4, ALL_CHANNELS),
        _flag("MANAGE_GUILD", 5),
        _flag("ADD_REACTIONS", 6, ALL_CHANNELS),
        _flag("VIEW_AUDIT_LOG", 7),
        _flag("PRIORITY_SPEAKER", 8, VOICE),
        _flag("STREAM", 9, VOICE_STAGE),
        _flag("VIEW_CHANNEL", 10, ALL_CHANNELS),
        _flag("SEND_MESSAGES", 11, ALL_CHANNELS),
        _flag("SEND_TTS_MESSAGES", 12, ALL_CHANNELS),
        _flag("MANAGE_MESSAGES", 13, ALL_CHANNELS),
        _flag("EMBED_LINKS", 14, ALL_CHANNELS),
        _flag("ATTACH_FILES", 15, ALL_CHANNELS),
        _flag("READ_MESSAGE_HISTORY", 16, ALL_CHANNELS),
        _flag("MENTION_EVERYONE", 17, ALL_CHANNELS),
        _flag("USE_EXTERNAL_EMOJIS", 18, ALL_CHANNELS),
        _flag("VIEW_GUILD_INSIGHTS", 19),
        _flag("CONNECT", 20, VOICE_STAGE),
        _flag("SPEAK", 21, VOICE),
        _flag("MUTE_MEMBERS", 22, VOICE_STAGE),
        _flag("DEAFEN_MEMBERS", 23, VOICE),
        _flag("MOVE_MEMBERS", 24, VOICE_STAGE),
        _flag("USE_VAD", 25, VOICE),
        _flag("CHANGE_NICKNAME", 26),
        _flag("MANAGE_NICKNAMES", 27),
        _flag("MANAGE_ROLES", 28, ALL_CHANNELS),
        _flag("MANAGE_WEBHOOKS", 29, ALL_CHANNELS),
        _flag("MANAGE_GUILD_EXPRESSIONS", 30),
        _flag("USE_APPLICATION_COMMANDS", 31, ALL_CHANNELS),
        _flag("REQUEST_TO_SPEAK", 32, STAGE),
        _flag("MANAGE_EVENTS", 33, VOICE_STAGE),
        _flag("MANAGE_THREADS", 34, TEXT),
        _flag("CREATE_PUBLIC_THREADS", 35, TEXT),
        _flag("CREATE_PRIVATE_THREADS", 36, TEXT),
        _flag("USE_EXTERNAL_STICKERS", 37, ALL_CHANNELS),
        _flag("SEND_MESSAGES_IN_THREADS", 38, TEXT),
        _flag("USE_EMBEDDED_ACTIVITIES", 39, TEXT_VOICE),
        _flag("MODERATE_MEMBERS", 40),
        _flag("VIEW_CREATOR_MONETIZATION_ANALYTICS", 41),
        _flag("USE_SOUNDBOARD", 42, VOICE),
        _flag("CREATE_GUILD_EXPRESSIONS", 43),
        _flag("CREATE_EVENTS", 44, VOICE_STAGE),
        _flag("USE_EXTERNAL_SOUNDS", 45, VOICE),
        _flag("SEND_VOICE_MESSAGES", 46, ALL_CHANNELS),
        _flag("SET_VOICE_CHANNEL_STATUS", 48, VOICE),
        _flag("SEND_POLLS", 49, ALL_CHANNELS),
        _flag("USE_EXTERNAL_APPS", 50, ALL_CHANNELS),
        _flag("PIN_MESSAGES", 51, TEXT),
        _flag("BYPASS_SLOWMODE", 52, ALL_CHANNELS),
    ),
)
