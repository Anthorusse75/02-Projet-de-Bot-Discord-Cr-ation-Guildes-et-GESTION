from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from did.portability.artifact import PortableArtifact, artifact_from_bytes, artifact_to_bytes


class KeyUnavailable(RuntimeError):
    pass


class KeyProvider(Protocol):
    @property
    def current_version(self) -> int: ...

    def key(self, version: int) -> bytes: ...


class InMemoryKeyProvider:
    def __init__(self, keys: dict[int, bytes], *, current_version: int) -> None:
        if current_version not in keys:
            raise ValueError("current artifact key version is unavailable")
        if any(version <= 0 or len(key) != 32 for version, key in keys.items()):
            raise ValueError("artifact master keys must be versioned AES-256 keys")
        self._keys = dict(keys)
        self._current_version = current_version

    @property
    def current_version(self) -> int:
        return self._current_version

    def key(self, version: int) -> bytes:
        try:
            return self._keys[version]
        except KeyError as exc:
            raise KeyUnavailable("artifact key version is unavailable") from exc

    @classmethod
    def from_base64(cls, value: str, *, version: int) -> InMemoryKeyProvider:
        try:
            key = base64.urlsafe_b64decode(value.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise ValueError("artifact encryption key is invalid") from exc
        return cls({version: key}, current_version=version)

    @classmethod
    def from_base64_keyring(
        cls,
        value: str,
        *,
        version: int,
        previous: dict[int, str],
    ) -> InMemoryKeyProvider:
        encoded = {**previous, version: value}
        keys: dict[int, bytes] = {}
        try:
            for key_version, material in encoded.items():
                keys[key_version] = base64.urlsafe_b64decode(material.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise ValueError("artifact encryption keyring is invalid") from exc
        return cls(keys, current_version=version)


@dataclass(frozen=True, slots=True)
class EncryptedArtifact:
    ciphertext: bytes
    nonce: bytes
    wrapped_dek: bytes
    wrap_nonce: bytes
    key_version: int
    content_hash: str


class ArtifactCipher:
    """AES-256-GCM envelope encryption with identity-bound authenticated metadata."""

    def __init__(self, provider: KeyProvider) -> None:
        self._provider = provider

    @staticmethod
    def _aad(
        *,
        artifact_id: UUID,
        owner_user_id: int,
        schema_version: str,
        key_version: int,
        content_hash: str,
    ) -> bytes:
        return json.dumps(
            {
                "artifact_id": str(artifact_id),
                "owner_user_id": str(owner_user_id),
                "schema_version": schema_version,
                "key_version": key_version,
                "content_hash": content_hash,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def encrypt(
        self, artifact: PortableArtifact, *, artifact_id: UUID, owner_user_id: int
    ) -> EncryptedArtifact:
        if owner_user_id <= 0:
            raise ValueError("artifact owner must be positive")
        key_version = self._provider.current_version
        aad = self._aad(
            artifact_id=artifact_id,
            owner_user_id=owner_user_id,
            schema_version=artifact.schema_version,
            key_version=key_version,
            content_hash=artifact.content_hash,
        )
        dek = AESGCM.generate_key(bit_length=256)
        nonce = os.urandom(12)
        wrap_nonce = os.urandom(12)
        ciphertext = AESGCM(dek).encrypt(nonce, artifact_to_bytes(artifact), aad)
        wrapped_dek = AESGCM(self._provider.key(key_version)).encrypt(wrap_nonce, dek, aad)
        return EncryptedArtifact(
            ciphertext, nonce, wrapped_dek, wrap_nonce, key_version, artifact.content_hash
        )

    def decrypt(
        self,
        encrypted: EncryptedArtifact,
        *,
        artifact_id: UUID,
        owner_user_id: int,
        schema_version: str,
    ) -> PortableArtifact:
        aad = self._aad(
            artifact_id=artifact_id,
            owner_user_id=owner_user_id,
            schema_version=schema_version,
            key_version=encrypted.key_version,
            content_hash=encrypted.content_hash,
        )
        try:
            dek = AESGCM(self._provider.key(encrypted.key_version)).decrypt(
                encrypted.wrap_nonce, encrypted.wrapped_dek, aad
            )
            plaintext = AESGCM(dek).decrypt(encrypted.nonce, encrypted.ciphertext, aad)
        except InvalidTag as exc:
            raise ValueError("portable artifact integrity check failed") from exc
        artifact = artifact_from_bytes(plaintext)
        if (
            artifact.schema_version != schema_version
            or artifact.content_hash != encrypted.content_hash
        ):
            raise ValueError("portable artifact authenticated metadata mismatch")
        return artifact

    def reencrypt(
        self,
        encrypted: EncryptedArtifact,
        *,
        artifact_id: UUID,
        owner_user_id: int,
        schema_version: str,
    ) -> EncryptedArtifact:
        artifact = self.decrypt(
            encrypted,
            artifact_id=artifact_id,
            owner_user_id=owner_user_id,
            schema_version=schema_version,
        )
        return self.encrypt(artifact, artifact_id=artifact_id, owner_user_id=owner_user_id)
