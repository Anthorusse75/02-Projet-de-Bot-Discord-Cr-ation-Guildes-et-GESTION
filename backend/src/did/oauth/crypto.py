import base64
import binascii
import secrets
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from did.oauth.models import EncryptedTokenSet, OAuthGrantRecord, OAuthTokenSet


class TokenEncryptionError(ValueError):
    pass


def decode_encryption_key(encoded: str) -> bytes:
    try:
        padding = "=" * (-len(encoded) % 4)
        key = base64.urlsafe_b64decode(encoded + padding)
    except (ValueError, binascii.Error) as exc:
        raise TokenEncryptionError("OAuth token encryption key is not valid base64url") from exc
    if len(key) != 32:
        raise TokenEncryptionError("OAuth token encryption key must decode to 32 bytes")
    return key


@dataclass(frozen=True, slots=True)
class TokenCipher:
    key: bytes
    key_version: int

    def __post_init__(self) -> None:
        if len(self.key) != 32:
            raise TokenEncryptionError("AES-256-GCM requires a 32-byte key")
        if self.key_version <= 0:
            raise TokenEncryptionError("key_version must be positive")

    def encrypt(self, *, discord_user_id: int, tokens: OAuthTokenSet) -> EncryptedTokenSet:
        access_nonce = secrets.token_bytes(12)
        refresh_nonce = secrets.token_bytes(12)
        aes = AESGCM(self.key)
        return EncryptedTokenSet(
            access_token_ciphertext=aes.encrypt(
                access_nonce,
                tokens.access_token.encode(),
                self._aad(discord_user_id, "access"),
            ),
            access_token_nonce=access_nonce,
            refresh_token_ciphertext=aes.encrypt(
                refresh_nonce,
                tokens.refresh_token.encode(),
                self._aad(discord_user_id, "refresh"),
            ),
            refresh_token_nonce=refresh_nonce,
            key_version=self.key_version,
        )

    def decrypt_access(self, grant: OAuthGrantRecord) -> str:
        return self._decrypt(
            grant,
            ciphertext=grant.access_token_ciphertext,
            nonce=grant.access_token_nonce,
            label=b"access",
        )

    def decrypt_refresh(self, grant: OAuthGrantRecord) -> str:
        return self._decrypt(
            grant,
            ciphertext=grant.refresh_token_ciphertext,
            nonce=grant.refresh_token_nonce,
            label=b"refresh",
        )

    def _decrypt(
        self,
        grant: OAuthGrantRecord,
        *,
        ciphertext: bytes,
        nonce: bytes,
        label: bytes,
    ) -> str:
        if grant.key_version != self.key_version:
            raise TokenEncryptionError("OAuth token key version is unavailable")
        try:
            plaintext = AESGCM(self.key).decrypt(
                nonce,
                ciphertext,
                self._aad(grant.discord_user_id, label.decode()),
            )
        except Exception as exc:
            raise TokenEncryptionError("OAuth token envelope authentication failed") from exc
        return plaintext.decode()

    def _aad(self, discord_user_id: int, token_kind: str) -> bytes:
        return f"did:oauth:{discord_user_id}:{token_kind}:v{self.key_version}".encode()
