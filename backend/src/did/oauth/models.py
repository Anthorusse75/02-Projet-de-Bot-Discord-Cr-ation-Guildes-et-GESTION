from dataclasses import dataclass
from datetime import datetime

OAUTH_SCOPES = frozenset({"identify", "guilds"})
OAUTH_SCOPE_PARAMETER = "identify guilds"


@dataclass(frozen=True, slots=True)
class DiscordUser:
    discord_user_id: int
    username: str
    global_name: str | None
    avatar_hash: str | None


@dataclass(frozen=True, slots=True)
class DiscordGuild:
    guild_id: int
    name: str
    icon_hash: str | None
    owner: bool
    permissions: int


@dataclass(frozen=True, slots=True)
class OAuthTokenSet:
    access_token: str
    refresh_token: str
    expires_at: datetime
    scopes: frozenset[str]


@dataclass(frozen=True, slots=True)
class OAuthGrantRecord:
    discord_user_id: int
    scopes: frozenset[str]
    access_token_ciphertext: bytes
    access_token_nonce: bytes
    access_token_expires_at: datetime
    refresh_token_ciphertext: bytes
    refresh_token_nonce: bytes
    key_version: int
    row_version: int
    revoked_at: datetime | None


@dataclass(frozen=True, slots=True)
class EncryptedTokenSet:
    access_token_ciphertext: bytes
    access_token_nonce: bytes
    refresh_token_ciphertext: bytes
    refresh_token_nonce: bytes
    key_version: int
