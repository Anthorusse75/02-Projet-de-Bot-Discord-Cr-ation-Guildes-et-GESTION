from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from did.oauth.crypto import TokenCipher, TokenEncryptionError, decode_encryption_key
from did.oauth.models import OAuthGrantRecord, OAuthTokenSet


def _grant(cipher: TokenCipher) -> tuple[OAuthGrantRecord, OAuthTokenSet]:
    tokens = OAuthTokenSet(
        access_token="access-value-never-logged",
        refresh_token="refresh-value-never-logged",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        scopes=frozenset({"identify", "guilds"}),
    )
    encrypted = cipher.encrypt(discord_user_id=42, tokens=tokens)
    grant = OAuthGrantRecord(
        discord_user_id=42,
        scopes=tokens.scopes,
        access_token_ciphertext=encrypted.access_token_ciphertext,
        access_token_nonce=encrypted.access_token_nonce,
        access_token_expires_at=tokens.expires_at,
        refresh_token_ciphertext=encrypted.refresh_token_ciphertext,
        refresh_token_nonce=encrypted.refresh_token_nonce,
        key_version=encrypted.key_version,
        row_version=1,
        revoked_at=None,
    )
    return grant, tokens


def test_token_envelope_round_trip_and_no_plaintext_at_rest() -> None:
    cipher = TokenCipher(b"k" * 32, 7)
    grant, tokens = _grant(cipher)
    assert tokens.access_token.encode() not in grant.access_token_ciphertext
    assert tokens.refresh_token.encode() not in grant.refresh_token_ciphertext
    assert cipher.decrypt_access(grant) == tokens.access_token
    assert cipher.decrypt_refresh(grant) == tokens.refresh_token


def test_token_envelope_is_bound_to_user_version_and_ciphertext() -> None:
    cipher = TokenCipher(b"k" * 32, 7)
    grant, _ = _grant(cipher)
    with pytest.raises(TokenEncryptionError, match="version"):
        TokenCipher(b"k" * 32, 8).decrypt_refresh(grant)
    tampered = replace(
        grant,
        refresh_token_ciphertext=grant.refresh_token_ciphertext[:-1]
        + bytes([grant.refresh_token_ciphertext[-1] ^ 1]),
    )
    with pytest.raises(TokenEncryptionError, match="authentication"):
        cipher.decrypt_refresh(tampered)


def test_encryption_key_requires_base64url_encoded_32_bytes() -> None:
    assert decode_encryption_key("a2tra2tra2tra2tra2tra2tra2tra2tra2tra2tra2s") == b"k" * 32
    with pytest.raises(TokenEncryptionError):
        decode_encryption_key("short")
